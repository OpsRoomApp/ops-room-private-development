# OPS ROOM 0.25.53

OPS ROOM is a desktop operations console for Microsoft Flight Simulator 2024. It bundles simulator telemetry, MSFS SimConnect/FSUIPC7 fallback, VATSIM data, SimBrief flight plans, GSX ground services, announceable cabin audio, Black Box recording and replay, and a public release.

## Getting started

1. Install Microsoft Flight Simulator 2024 with the latest platform update.
2. Download the OPS ROOM Windows installer from the public release page.
3. Launch the application; the desktop host opens in your default browser.
4. On first run, set your SimBrief Pilot ID and your VATSIM callsign in Settings.
5. Fetch the latest OFP, then load your aircraft and start flying.

## Supported aircraft telemetry

OPS ROOM recognises the Fenix A320, PMDG 777, iniBuilds A300 / A340 / A350 and FlyByWire A32NX / A380X airframes out of the box. SimConnect is the primary telemetry source and FSUIPC7 is used as an automatic fallback when configured.

## PMDG 777

The PMDG 777 SDK is bundled under its own EULA. OPS ROOM accepts the PMDG SDK EULA explicitly the first time the SDK is used; the SDK only enables while that acceptance is recorded locally. Reinstallation is required only if you want to remove the PMDG telemetry path entirely.

## Updates

OPS ROOM checks public GitHub releases on launch. New public releases appear as a notification; the in-app updater installs them with your confirmation. Old versions stay bootable while an update is staged.

See `RELEASE_NOTES.md` for 0.25.53 highlights.
