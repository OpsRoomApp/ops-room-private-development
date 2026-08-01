# OPS ROOM Black Box design credits

The Black Box recorder and replay are an original OPS ROOM implementation. No GPL-licensed source code was copied into OPS ROOM.

The design was informed by these public projects:

- **SkyDolly (Sky Dolly)** by Oliver Knoll — recording/replay workflow, automatic or variable sampling, replay speed, seeking, looping, separate persistent logbook recordings, position/attitude/control capture, heading-aware interpolation, and portable export concepts. Sky Dolly is MIT licensed. https://github.com/till213/SkyDolly
- **MSFS2020 PilotPathRecorder** by Stephen Adam Horowitz — KML/Google Earth flight-path review and portable path export concepts. MIT licensed. https://github.com/SAHorowitz/MSFS2020-PilotPathRecorder
- **MSFS Landing Inspector** by mracko — browser-oriented review of recorded flight/landing data. MIT licensed. https://github.com/mracko/MSFS-Landing-Inspector

The following projects were reviewed only as architectural references. Their code was not copied because their licences or architecture do not match OPS ROOM's distribution model:

- Flight Recorder — https://github.com/nguyenquyhy/Flight-Recorder
- SaltyReplay — https://github.com/saltysimulations/saltyreplay
- FS Tool — https://github.com/Elephant42/FS_Tool
- msfs_logger_replay — https://github.com/ijl20/msfs_logger_replay

OPS ROOM uses Microsoft Flight Simulator's documented SimConnect events and standard simulation variables for replay. In-simulator replay is aircraft-dependent: standard position, attitude and control variables are applied where the loaded aircraft exposes them as writable. Aircraft-specific internal systems are not fabricated.
