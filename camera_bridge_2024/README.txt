OPS ROOM Camera Bridge 2024

Native helper for MSFS 2024 FIDS click-to-follow camera testing in the OPS ROOM public beta RC.

Build on the simulator PC with:
  BUILD CAMERA BRIDGE 2024.bat

Required local paths:
  C:\MSFS 2024 SDK\SimConnect SDK\include\SimConnect.h
  C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.lib
  C:\Program Files\Microsoft Visual Studio\2022\Community

The bridge writes logs to:
  %LOCALAPPDATA%\Ops Room\logs\camera_bridge_2024.log

It polls OPS ROOM on port 8080 and follows the selected FIDS target only when MSFS 2024 exposes the new add-on Camera API. MSFS 2020 is intentionally not driven by this helper.


RC2 note: the Camera Bridge stays open and retries SimConnect every 5 seconds, releases back toward the user aircraft, and retries camera-owner acquisition after MSFS Addons panel disable/enable.
