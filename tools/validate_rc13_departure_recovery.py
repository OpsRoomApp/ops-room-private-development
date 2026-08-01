from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import gsx_remote as g  # noqa: E402

passed: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


def sha_file(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def function_sources(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(True)
    tree = ast.parse(source)
    return {
        node.name: "".join(lines[node.lineno - 1:node.end_lineno])
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# Exact RC10 hashes. These prove the working subsystems and the service/Fenix
# orchestration functions were not replaced by RC11/RC12 implementations.
protected_files = {
    "app/announcements.py": "721f55088def610f5d66e5dddd3a00123a86ccba10e4f2c2d654dedd1284da1b",
    "app/telemetry_provider.py": "0c921fe33d076d68db66d479bb3db5388c844924924d7995358bdafe21c91de8",
    "app/fenix_adapter.py": "7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46",
    "app/fenix_gsx_loading_state_machine.py": "6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd",
    "app/pirep_analysis.py": "a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a",
    "app/economy.py": "7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87",
    "app/settings_store.py": "0bd2117c4a8412d113047514986f06e8552bc3508b91ef834cdce3d5aa26af05",
    "app/raas.py": "7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b",
}
for rel, expected in protected_files.items():
    check(sha_file(rel) == expected, f"RC10 protected file is byte-identical: {rel}")

critical_function_hashes = {
    "_trigger_service_remote_v2": "c32f9c692336836d89c9fdc998fdcc0a8bd0ab4142f5387245d9f752d5ac9ba9",
    "call_service": "025b62e36bf102d0fd30b90e66c752856925a06cf39ef4487925588f754d8705",
    "_request_once": "8ab29d6a15e19c09b682afbac651acd291d3ccdbb92c597a8b8c32261edaf639",
    "_request_fenix_loading_once": "2ee617802d0e09670d5a45d28b216d82e24c40541af2638864e46f420b11be48",
    "_service_plan_for_mode": "4476ecf42e967dc870bc1c3ffcab989c9984ace55ca3a906a653e7576f74f23e",
    "_automation_cycle": "6883fd3f4d749530290cc728de7a8c7e3d383fe86124b37e4872ac6ac20a21a7",
    "_apply_fenix_boarding_decision": "9e8d4a8915efe36f199739a44d782aa9eb1c2d5535cd39be405c78a72c39b8e3",
    "_block_if_fenix_refuel": "4d71a011c8ffe58d5fdffe76887f47676c7d4d5de18e67f36482a6c35a575cb6",
    "_request_arrival_service_when_available": "76db7e15c4098462cc5219ecde8c42ffac0aab1b6bdace1c0cb74bd4215c577e",
    "_maybe_retry_arrival_cleaning_once": "c02a960f42cbd6fd68af2a0d8c164d222cea3ded23089003f2d92a8b96f5a7c8",
}
functions = function_sources(ROOT / "app" / "gsx_remote.py")
for name, expected in critical_function_hashes.items():
    actual = hashlib.sha256(functions[name].encode("utf-8")).hexdigest()
    check(actual == expected, f"RC10 service/Fenix orchestration function is unchanged: {name}")

# Remote API menu arrays remain aligned to the raw entries positions, while the
# RC10 display options shape remains filtered exactly as before.
state = {
    "menuShown": True,
    "menu": {
        "title": "",
        "entries": ["Aerogate", "", "ASIG", "EFM", "LOSCH [GSX choice]", "Condor", "Lufthansa", "Back"],
        "iconWide": [True, False, True, True, True, True, True, False],
        "disabled": [False, False, False, False, False, False, False, False],
    },
}
parsed = g._official_menu_from_state(state)
check(parsed["options"] == ["Aerogate", "ASIG", "EFM", "LOSCH [GSX choice]", "Condor", "Lufthansa", "Back"], "Existing RC10 display menu remains filtered")
check(parsed["raw_options"][6] == "Lufthansa" and parsed["option_indices"][-2] == 6, "Raw GSX menu index is preserved")
check(len(parsed["raw_disabled"]) == len(parsed["raw_options"]), "disabled[] remains aligned with menu.entries")
check(len(parsed["raw_icon_wide"]) == len(parsed["raw_options"]), "iconWide[] remains aligned with menu.entries")

menu = {
    "available": True,
    "title": "",
    "raw_options": ["Aerogate", "ASIG", "EFM", "LOSCH [GSX choice]", "Condor", "Lufthansa", "Back"],
    "raw_disabled": [False] * 7,
    "raw_icon_wide": [True, True, True, True, True, True, False],
    "options": ["Aerogate", "ASIG", "EFM", "LOSCH [GSX choice]", "Condor", "Lufthansa", "Back"],
}
live_dlh = {"airline": "Deutsche Lufthansa AG", "callsign": "DLH06V"}
check(g._probable_operator_menu(menu), "The real GSX company menu is recognized without relying on its title")
choice = g._operator_observer_choice(menu, live_dlh)
check(choice is not None and choice["index"] == 5 and choice["label"] == "Lufthansa", "DLH06V selects Lufthansa at the current raw index 5")

close_menu = copy.deepcopy(menu)
close_menu["raw_options"] = ["Aerogate", "Lufthansa Technik", "LOSCH [GSX choice]", "Lufthansa", "Back"]
close_menu["raw_disabled"] = [False] * 5
close_menu["raw_icon_wide"] = [True, True, True, True, False]
close_menu["options"] = list(close_menu["raw_options"])
choice = g._operator_observer_choice(close_menu, live_dlh)
check(choice is not None and choice["index"] == 3 and choice["label"] == "Lufthansa", "Plain Lufthansa wins over Lufthansa Technik")

disabled_menu = copy.deepcopy(menu)
disabled_menu["raw_disabled"][5] = True
disabled_choice = g._operator_observer_choice(disabled_menu, live_dlh)
check(disabled_choice is not None and disabled_choice["index"] == 3 and disabled_choice.get("fallback"), "A disabled Lufthansa entry falls back only to the explicit GSX choice")

unknown = g._operator_observer_choice(menu, {"airline": "Example Virtual", "callsign": "ZZZ123"})
check(unknown is not None and unknown["index"] == 3 and unknown.get("fallback"), "No clear airline match selects the explicit [GSX choice] entry")
no_default = copy.deepcopy(menu)
no_default["raw_options"] = ["Aerogate", "ASIG", "EFM", "Condor", "Back"]
no_default["raw_disabled"] = [False] * 5
no_default["raw_icon_wide"] = [True, True, True, True, False]
no_default["options"] = list(no_default["raw_options"])
check(g._operator_observer_choice(no_default, {"airline": "Example Virtual", "callsign": "ZZZ123"}) is None, "No match and no explicit GSX choice never selects the first company")

top_level = {
    "available": True,
    "title": "Activate Services at EDDF",
    "raw_options": ["Request Catering", "Request Refueling", "Request Boarding", "Back"],
    "raw_disabled": [False] * 4,
    "raw_icon_wide": [True, True, False, False],
    "options": ["Request Catering", "Request Refueling", "Request Boarding", "Back"],
}
check(not g._probable_operator_menu(top_level), "Top-level service menu cannot be mistaken for an operator menu")

# The shared RC10 resolver must not select [GSX choice] synchronously. It exits
# successfully and leaves the operator observer completely outside service status.
original_select = g.select_menu_by_label
original_observer_ready = g._operator_observer_ready
def forbidden_select(*_args, **_kwargs):
    raise AssertionError("operator menu must not be selected by the shared resolver")
g.select_menu_by_label = forbidden_select
g._operator_observer_ready = lambda: True
observer_menu = copy.deepcopy(menu)
observer_menu["source"] = "official-remote-api-v2"
try:
    result = g._resolve_followups({"ok": True, "menu": observer_menu}, "catering")
    check(result.get("ok") is True and not result.get("requires_selection") and result.get("selections") == [], "Official operator menu is isolated from service acknowledgement and latches")
finally:
    g.select_menu_by_label = original_select
    g._operator_observer_ready = original_observer_ready

# If the observer cannot start, the legacy synchronous follow-up remains safe: it
# selects Lufthansa from live GSX SimBrief, or only the explicit [GSX choice]
# fallback. It never chooses the first company.
original_select = g.select_menu_by_label
original_observer_ready = g._operator_observer_ready
original_official_state = copy.deepcopy(g._OFFICIAL_STATE)
selected_labels: list[str] = []
g.select_menu_by_label = lambda expected, aliases=(): (selected_labels.append(str(expected)) or {"ok": True, "selected": expected, "menu": {"available": False, "options": []}})
g._operator_observer_ready = lambda: False
try:
    g._OFFICIAL_STATE = {"handlerData": {"simbrief": live_dlh}}
    sync_menu = copy.deepcopy(menu)
    sync_menu["source"] = "official-remote-api-v2"
    sync_result = g._resolve_followups({"ok": True, "menu": sync_menu}, "catering", max_steps=1)
    check(sync_result.get("ok") is True and selected_labels == ["Lufthansa"], "Observer failure falls back to a synchronous Lufthansa pick without blocking the service")
    selected_labels.clear()
    g._OFFICIAL_STATE = {"handlerData": {"simbrief": {"airline": "Example Virtual", "callsign": "ZZZ123"}}}
    sync_result = g._resolve_followups({"ok": True, "menu": sync_menu}, "catering", max_steps=1)
    check(sync_result.get("ok") is True and selected_labels == ["LOSCH [GSX choice]"], "Unknown airline falls back only to the explicit GSX choice when the observer is unavailable")
finally:
    g.select_menu_by_label = original_select
    g._operator_observer_ready = original_observer_ready
    g._OFFICIAL_STATE = original_official_state

# Planning a legacy title-based operator choice has no memory side effect; memory
# moves only after a confirmed pick result.
old_selected = g._LAST_SELECTED_OPERATOR
old_flight = g._LAST_SELECTED_OPERATOR_FLIGHT
try:
    g._LAST_SELECTED_OPERATOR = ""
    g._LAST_SELECTED_OPERATOR_FLIGHT = ""
    _ = g._preferred_operator_option_index("Select Handling Operator", menu["options"])
    check(g._LAST_SELECTED_OPERATOR == "" and g._LAST_SELECTED_OPERATOR_FLIGHT == "", "Operator is not remembered while only calculating an index")
finally:
    g._LAST_SELECTED_OPERATOR = old_selected
    g._LAST_SELECTED_OPERATOR_FLIGHT = old_flight

# Static isolation guard: the observer cannot invoke or mutate any service/Fenix
# sequence primitives.
observer_source = functions["_operator_observer_worker"]
for forbidden in (
    "call_service(", "_request_once(", "_mark_service_requested(",
    "_request_fenix_loading_once(", "fenix_start_gsx_boarding(",
    "_AUTOMATION[\"requested\"]", "_AUTOMATION_REQUESTED_MONO",
):
    check(forbidden not in observer_source, f"Operator observer is isolated from {forbidden}")
check('"id": command_id' in observer_source and 'str(msg.get("id") or "") == str(pending.get("id") or "")' in observer_source, "menu.pick uses unique command/result correlation")
check('"args": {"index": int(choice["index"])}' in observer_source, "menu.pick uses the latest raw menu.entries position")
check("attempted_decisions.clear()" in observer_source and "current_menu_fingerprint = \"\"" in observer_source, "Identical operator menus are eligible again after the prior popup closes")
check("_OPERATOR_OBSERVER_CONNECTED.set()" in observer_source, "Observer readiness requires a live GSX Remote API connection")

# Deterministic fake WebSocket: subscribe acknowledgement has no id, the operator
# command has a unique id, and only the matching result confirms memory.
import websockets.sync.client  # noqa: E402

class DummySocket:
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False

class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.queue = [
            json.dumps({"type": "result", "ok": True}),  # subscribe result; must be ignored
            json.dumps({
                "type": "snapshot",
                "menuShown": True,
                "menu": {
                    "title": "",
                    "entries": menu["raw_options"],
                    "iconWide": menu["raw_icon_wide"],
                    "disabled": menu["raw_disabled"],
                },
                "handlerData": {"simbrief": live_dlh},
            }),
        ]
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def send(self, value: str):
        payload = json.loads(value)
        self.sent.append(payload)
        if payload.get("verb") == "menu.pick":
            pick_count = len([item for item in self.sent if item.get("verb") == "menu.pick"])
            if pick_count == 1:
                self.queue.append(json.dumps({"type": "result", "id": "wrong-id", "ok": True}))
            self.queue.append(json.dumps({"type": "result", "id": payload["id"], "ok": True}))
            if pick_count == 1:
                # The same company menu can reopen for another service. Closing
                # the first popup must reset the per-popup de-duplication state.
                self.queue.append(json.dumps({"type": "patch", "path": "/menuShown", "value": False}))
                self.queue.append(json.dumps({"type": "patch", "path": "/menu", "value": {
                    "title": "",
                    "entries": menu["raw_options"],
                    "iconWide": menu["raw_icon_wide"],
                    "disabled": menu["raw_disabled"],
                }}))
                self.queue.append(json.dumps({"type": "patch", "path": "/menuShown", "value": True}))
    def recv(self, timeout=None):
        if self.queue:
            return self.queue.pop(0)
        g._OPERATOR_OBSERVER_STOP.set()
        raise TimeoutError()

fake = FakeWebSocket()
orig_connect = websockets.sync.client.connect
orig_socket = g.socket.create_connection
orig_candidates = g._official_candidates
orig_signature = g._current_operator_flight_signature
orig_automation = copy.deepcopy(g._AUTOMATION)
old_selected = g._LAST_SELECTED_OPERATOR
old_flight = g._LAST_SELECTED_OPERATOR_FLIGHT
try:
    websockets.sync.client.connect = lambda *_args, **_kwargs: fake
    g.socket.create_connection = lambda *_args, **_kwargs: DummySocket()
    g._official_candidates = lambda: ["http://127.0.0.1:8744/"]
    g._current_operator_flight_signature = lambda: "DLH|06V|EDDF|EDDM"
    g._LAST_SELECTED_OPERATOR = ""
    g._LAST_SELECTED_OPERATOR_FLIGHT = ""
    g._AUTOMATION.clear()
    g._AUTOMATION.update({"running": True, "session_generation": 130, "latches": {}, "history": [], "requested": []})
    g._OPERATOR_OBSERVER_STOP.clear()
    g._operator_observer_worker(130)
    picks = [item for item in fake.sent if item.get("verb") == "menu.pick"]
    check(len(picks) == 2 and all(item["args"]["index"] == 5 for item in picks), "Observer selects Lufthansa once for each of two identical successive operator popups")
    command_ids = [str(item.get("id") or "") for item in picks]
    check(all(value.startswith("ops-operator-130-") for value in command_ids) and len(set(command_ids)) == 2, "Every operator pick has a distinct correlation id")
    check(g._LAST_SELECTED_OPERATOR == "Lufthansa" and g._LAST_SELECTED_OPERATOR_FLIGHT == "DLH|06V|EDDF|EDDM", "Only matching successful results remember Lufthansa")
finally:
    websockets.sync.client.connect = orig_connect
    g.socket.create_connection = orig_socket
    g._official_candidates = orig_candidates
    g._current_operator_flight_signature = orig_signature
    g._AUTOMATION.clear()
    g._AUTOMATION.update(orig_automation)
    g._LAST_SELECTED_OPERATOR = old_selected
    g._LAST_SELECTED_OPERATOR_FLIGHT = old_flight
    g._OPERATOR_OBSERVER_STOP.clear()
    g._OPERATOR_OBSERVER_CONNECTED.clear()

version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
check(version["version"] == "0.24.48" and version["build"].endswith("18"), "Version metadata preserves RC13 recovery in v0.24.48 RC18")
check("OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Complete build script targets the RC18 Windows ZIP")
notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
check("New in v0.24.48" in notes and "RC10-based Departure Services/Fenix recovery" in notes, "Release notes retain the RC10-based departure recovery baseline")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
