from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path


def _app_data_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "Ops Room"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_update_state(payload: dict) -> None:
    try:
        data = dict(payload)
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (_app_data_dir() / "update_state.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


class UpdaterStatusWindow:
    """Small visible updater window so installation is not silent.

    It intentionally uses only tkinter from the standard library. If tkinter is
    unavailable, the updater still runs and uses the existing MessageBox fallback
    for failures.
    """

    def __init__(self, version: str = "") -> None:
        self.version = version
        self.enabled = False
        self.root = None
        self.title_var = None
        self.detail_var = None
        self.progress = None
        self.log_box = None
        self._indeterminate = False
        try:
            import tkinter as tk
            from tkinter import ttk

            self.tk = tk
            self.ttk = ttk
            root = tk.Tk()
            root.title("OPS ROOM Updater")
            root.geometry("560x300")
            root.resizable(False, False)
            root.protocol("WM_DELETE_WINDOW", lambda: None)
            try:
                root.attributes("-topmost", True)
                root.after(1500, lambda: root.attributes("-topmost", False))
            except Exception:
                pass

            frame = ttk.Frame(root, padding=18)
            frame.pack(fill="both", expand=True)
            header = ttk.Label(frame, text=f"Installing OPS ROOM {('v' + version) if version else 'update'}", font=("Segoe UI", 14, "bold"))
            header.pack(anchor="w")
            self.title_var = tk.StringVar(value="Preparing update")
            self.detail_var = tk.StringVar(value="Please wait. OPS ROOM will restart automatically.")
            ttk.Label(frame, textvariable=self.title_var, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(18, 2))
            ttk.Label(frame, textvariable=self.detail_var, wraplength=510).pack(anchor="w")
            self.progress = ttk.Progressbar(frame, mode="indeterminate", length=510)
            self.progress.pack(fill="x", pady=(18, 12))
            self.progress.start(12)
            self._indeterminate = True
            self.log_box = tk.Text(frame, height=5, wrap="word", borderwidth=1, relief="solid")
            self.log_box.pack(fill="both", expand=True)
            self.log_box.configure(state="disabled")
            self.root = root
            self.enabled = True
            self._flush()
        except Exception:
            self.enabled = False

    def _flush(self) -> None:
        if not self.enabled or not self.root:
            return
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            self.enabled = False

    def set(self, title: str, detail: str = "", percent: int | None = None) -> None:
        if self.title_var is not None:
            self.title_var.set(title)
        if self.detail_var is not None:
            self.detail_var.set(detail or "Please wait. OPS ROOM will restart automatically.")
        if self.progress is not None:
            try:
                if percent is None:
                    if not self._indeterminate:
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                        self._indeterminate = True
                else:
                    if self._indeterminate:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=100)
                        self._indeterminate = False
                    self.progress["value"] = max(0, min(100, percent))
            except Exception:
                pass
        if self.log_box is not None:
            try:
                self.log_box.configure(state="normal")
                stamp = time.strftime("%H:%M:%S")
                self.log_box.insert("end", f"[{stamp}] {title}\n")
                if detail:
                    self.log_box.insert("end", f"          {detail}\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except Exception:
                pass
        self._flush()

    def close(self, delay: float = 0.0) -> None:
        if delay:
            end = time.monotonic() + delay
            while time.monotonic() < end:
                self._flush()
                time.sleep(0.05)
        if self.enabled and self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.enabled = False


def wait_for_pid(pid: int, timeout: float = 60.0, ui: UpdaterStatusWindow | None = None) -> bool:
    if ui:
        ui.set("Waiting for OPS ROOM to close", "The app is closing before files are replaced.")
    if pid <= 0 or os.name != "nt":
        time.sleep(1.5)
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                return True
            try:
                result = ctypes.windll.kernel32.WaitForSingleObject(handle, 500)
                if result == 0:
                    return True
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            time.sleep(0.5)
            return False
        if ui:
            ui._flush()
    return False


def _norm(path: Path) -> str:
    try:
        return str(path.resolve()).rstrip('\\/').lower()
    except Exception:
        return str(path).rstrip('\\/').lower()


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def terminate_processes_from_install(target: Path, app_exe: Path, timeout: float = 45.0, ui: UpdaterStatusWindow | None = None) -> None:
    """Stop OPS ROOM processes still running from the install folder."""
    if ui:
        ui.set("Stopping old OPS ROOM processes", "Closing any remaining OPS ROOM runtime processes from the install folder.")
    if os.name != 'nt':
        return
    target_norm = _norm(target)
    app_norm = _norm(app_exe)
    ps = rf'''
$target = "{target_norm}"
$app = "{app_norm}"
$me = $PID
Get-CimInstance Win32_Process | Where-Object {{
  $_.ExecutablePath -and
  ($_.ExecutablePath.ToLower() -eq $app -or $_.ExecutablePath.ToLower().StartsWith($target + "\")) -and
  $_.ProcessId -ne $me
}} | ForEach-Object {{
  try {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }} catch {{}}
}}
'''
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        check = rf'''
$target = "{target_norm}"
$app = "{app_norm}"
$count = @(Get-CimInstance Win32_Process | Where-Object {{
  $_.ExecutablePath -and
  ($_.ExecutablePath.ToLower() -eq $app -or $_.ExecutablePath.ToLower().StartsWith($target + "\"))
}}).Count
Write-Output $count
'''
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', check], capture_output=True, text=True, timeout=20)
        try:
            if int((result.stdout or '0').strip().splitlines()[-1]) <= 0:
                return
        except Exception:
            return
        if ui:
            ui._flush()
        time.sleep(0.75)


def clear_update_state(version: str = "") -> None:
    """Remove cached updater state after a successful replacement."""
    try:
        state = _app_data_dir() / "update_state.json"
        if state.exists():
            state.unlink()
        if version:
            marker = state.with_name("last_update.json")
            marker.write_text(json.dumps({"installed_version": version, "cleared_at": int(time.time())}), encoding="utf-8")
    except Exception:
        pass


def retry_action(action, description: str, timeout: float = 120.0, ui: UpdaterStatusWindow | None = None) -> None:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            action()
            return
        except Exception as exc:
            last_exc = exc
            if ui:
                ui.set("Waiting for file lock", f"{description}: {exc}")
            time.sleep(0.5)
    if last_exc:
        raise PermissionError(f'{description} failed after waiting for file locks to clear: {last_exc}') from last_exc


def find_payload_root(extracted: Path) -> Path:
    direct = extracted / "OPS ROOM.exe"
    if direct.is_file():
        return extracted
    for child in extracted.iterdir():
        if child.is_dir() and (child / "OPS ROOM.exe").is_file():
            return child
    matches = list(extracted.rglob("OPS ROOM.exe"))
    if matches:
        return matches[0].parent
    raise FileNotFoundError("The update package does not contain OPS ROOM.exe.")


def copy_tree_merge(src: Path, dst: Path, ui: UpdaterStatusWindow | None = None) -> None:
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_tree_merge(item, target, ui=ui)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            retry_action(lambda i=item, t=target: shutil.copy2(i, t), f'Copy {item.name}', timeout=120.0, ui=ui)


def remove_for_update(target: Path, ui: UpdaterStatusWindow | None = None) -> None:
    preserve = {"Announcements"}
    for item in list(target.iterdir()):
        if item.name in preserve:
            continue
        if item.is_dir():
            retry_action(lambda p=item: shutil.rmtree(p), f'Remove folder {item}', timeout=120.0, ui=ui)
        else:
            retry_action(lambda p=item: p.unlink(missing_ok=True), f'Remove file {item}', timeout=120.0, ui=ui)


def _show_failure_message(message: str) -> None:
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "OPS ROOM Updater", 0x10)
        else:
            print(message, file=sys.stderr)
    except Exception:
        pass


def install_update(package: Path, target: Path, app_exe: Path, pid: int, version: str = "") -> int:
    ui = UpdaterStatusWindow(version=version)
    updater_executable = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    write_update_state({"stage": "updater_starting", "version": version, "package": str(package), "target": str(target), "updater": str(updater_executable)})
    work = Path(tempfile.mkdtemp(prefix="opsroom-update-"))
    extracted = work / "extracted"
    backup = target.with_name(f"{target.name}.backup")
    try:
        if _is_inside(updater_executable, target):
            raise PermissionError(f"Updater is running from the folder it must replace: {updater_executable}")

        wait_for_pid(pid, timeout=120.0, ui=ui)
        terminate_processes_from_install(target, app_exe, timeout=90.0, ui=ui)

        ui.set("Extracting update package", "Checking the downloaded OPS ROOM release package.")
        write_update_state({"stage": "extracting", "version": version, "package": str(package), "target": str(target)})
        extracted.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package) as zf:
            zf.extractall(extracted)
        payload = find_payload_root(extracted)

        ui.set("Creating backup", "Backing up the current OPS ROOM folder before replacement.")
        write_update_state({"stage": "backing_up", "version": version, "target": str(target), "backup": str(backup)})
        if backup.exists():
            retry_action(lambda: shutil.rmtree(backup), f'Remove old backup {backup}', timeout=120.0, ui=ui)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, backup, ignore=shutil.ignore_patterns("*.log", "*.tmp", "Announcements"), dirs_exist_ok=True)

        ui.set("Replacing old files", "Removing old application files while keeping user announcements.", percent=45)
        write_update_state({"stage": "replacing", "version": version, "target": str(target)})
        remove_for_update(target, ui=ui)

        ui.set("Installing new files", "Copying the new OPS ROOM release into place.", percent=65)
        write_update_state({"stage": "copying", "version": version, "target": str(target), "payload": str(payload)})
        copy_tree_merge(payload, target, ui=ui)

        new_default = payload / "Announcements" / "Default"
        if new_default.is_dir():
            ui.set("Updating default announcements", "Refreshing bundled default announcement audio.", percent=82)
            default_target = target / "Announcements" / "Default"
            if default_target.exists():
                retry_action(lambda: shutil.rmtree(default_target), f'Remove old default announcements {default_target}', timeout=120.0, ui=ui)
            shutil.copytree(new_default, default_target, dirs_exist_ok=True)

        ui.set("Finishing update", "Cleaning update state and preparing restart.", percent=95)
        write_update_state({"stage": "restarting", "version": version, "target": str(target), "app_exe": str(app_exe)})
        clear_update_state(version)
        if app_exe.is_file():
            subprocess.Popen([str(app_exe)], cwd=str(target), close_fds=True)
        ui.set("Update complete", "OPS ROOM is restarting now.", percent=100)
        ui.close(delay=1.5)
        return 0
    except Exception as exc:
        write_update_state({"stage": "failed", "version": version, "package": str(package), "target": str(target), "reason": f"{type(exc).__name__}: {exc}"})
        try:
            ui.set("Update failed", "Restoring the previous OPS ROOM version if possible.")
            if backup.exists():
                terminate_processes_from_install(target, app_exe, timeout=15.0, ui=ui)
                remove_for_update(target, ui=ui)
                copy_tree_merge(backup, target, ui=ui)
                if app_exe.is_file():
                    subprocess.Popen([str(app_exe)], cwd=str(target), close_fds=True)
        except Exception:
            pass
        message = f"OPS ROOM update failed. The previous version was restored if possible.\n\n{type(exc).__name__}: {exc}"
        ui.close(delay=0.5)
        _show_failure_message(message)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="OPS ROOM updater")
    parser.add_argument("--package", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--app-exe", required=True)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--version", default="")
    args = parser.parse_args()
    return install_update(Path(args.package), Path(args.target), Path(args.app_exe), args.pid, args.version)


if __name__ == "__main__":
    raise SystemExit(main())
