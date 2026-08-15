# OPS ROOM: A Complete Flight Operations Companion for Microsoft Flight Simulator

OPS ROOM is a free Windows companion for Microsoft Flight Simulator 2020 and 2024. It brings the main parts of an airline operation into one connected workspace, from flight planning and performance calculations to ground handling, live telemetry, replay, debriefing and airline management.

Rather than opening several unrelated tools before every flight, pilots can use OPS ROOM as a single operations centre that follows the flight from the first briefing screen to the final logbook entry. It runs alongside the simulator, in a normal browser, on a tablet or phone over LAN, and now inside the simulator through its own tablet-style toolbar panel.

## Plan the flight

The Briefing module imports the SimBrief operational flight plan and brings the important information together in one place. Pilots can review the route, weather, METAR and TAF data, live precipitation, FAA NOTAMs, charts and airport information before departure. Procedures provides aircraft checklists and flows, while Scratchpad keeps personal notes close to the flight.

The Performance module provides first-party takeoff and landing calculations across the supported fleet. It can produce V1, VR and V2, or VLS and VREF where appropriate, together with flap, trim, flex temperature, assumed temperature and runway distance guidance. Runway, wind, temperature, QNH and aircraft data can be filled from SimBrief, live weather and the simulator, leaving the pilot to review the result and provide the required ZFW CG value.

The Live OFP dispatch board compares the plan with what actually happens in the simulator. It records changes in times, fuel, weights, passenger and cargo figures through the different stages of the flight. The loadsheet can be signed with a typed or drawn electronic signature, and the completed flight is signed again after arrival before it is closed in the logbook.

## Run the operation

Ground Control connects with GSX to coordinate boarding, catering, water, pushback and arrival services. Service activity is recorded as receipts and linked to the flight, giving the dispatch and finance features a useful record of what happened on the ground.

The FIDS and dispatch views add an airline operations feel without separating the information into another application. Flight Watch provides a live view of the aircraft, simulator connection, position and flight state. OPS ROOM uses a shared telemetry path so Flight Watch, Black Box, Runway Awareness, announcements and flight analysis work from the same data. FSUIPC is used when available, with SimConnect available as a fallback.

Runway Awareness provides RAAS-style callouts and closure alerts. CPDLC through Hoppie supports controller-pilot datalink functions, including logon, messages and PDC requests. The Announcer handles cabin and operational announcements, with volume that follows the selected camera view.

## Record, replay and review

Black Box is a continuous flight data recorder built into OPS ROOM. It captures the flight path, aircraft movement, controls, engines, flight systems, autopilot, flaps and gear at different recording rates throughout the flight. The recorder also reconstructs landing performance, including touchdown speed, vertical speed, G-loading and bounce detection.

Recordings can be replayed inside the simulator with pause, resume, scrubbing, looping and playback speed controls. They can also be exported to CSV, GPX and KML for later review or use in other tools.

After landing, the Logbook and PIREP provide a detailed review of the flight. The analysis includes runway profiles, stability gates, touchdown information, score details and passenger satisfaction. Finances adds an airline and pilot economy with revenue, costs, GSX receipts, balances and passenger response to the quality of the landing and the operation.

## Maps, NOTAMs and airport information

The map combines the flight and aircraft position with weather radar, FAA NOTAMs, TFR and FDC information, airspace and local airport surface data such as taxiways, aprons and stands. NOTAMs can be reviewed from live data, the flight plan or a combined source, and closure markers can be installed as an MSFS Community package for both simulator versions. Runway and taxiway X markers, barricades and a lighted closure trailer can then be used with the in-sim closure features.

## Use OPS ROOM inside the simulator

The v0.25 release adds an in-game tablet panel for MSFS 2020 and 2024. A toolbar button opens the full OPS ROOM interface in a tablet-style frame, including the launcher and the complete module set. The panel connects to the OPS ROOM desktop app on the same PC, so it shows the same live information as the browser and external tablet views without requiring an alt-tab.

The Community package is included with the Windows distribution and can be installed automatically during setup or on first launch. If the desktop app is not running, the panel shows a clear start screen and reconnects when OPS ROOM becomes available. The package supports the Store and Steam Community folder locations for MSFS 2020 and 2024, with a folder selection option for Addons Linker users.

## Share the flight

The optional Discord integration provides Rich Presence with the current flight, callsign, route and phase. Pilots can choose whether to share takeoff and landing events, appear on the public leaderboard or be visible on the live community map. OBS Tools provide overlays for streamers who want to show flight information during a broadcast.

OPS ROOM also integrates with SimBrief, GSX, the Fenix A320, PMDG 777, FSUIPC, SimConnect, VATSIM and vPilot, ChartFox and Hoppie CPDLC. Aircraft adapters are available for supported add-on aircraft where additional aircraft data is required.

## v0.25 release

Version 0.25 adds the Black Box recorder and in-sim replay, the first-party performance calculator, Live OFP tracking with electronic crew sign-off, the in-game tablet panel and improved NOTAM closure markers. It also includes a shared telemetry path, improved GSX and Fenix handling, stronger flight analysis, community features and a broad reliability pass across the application.

OPS ROOM is freeware for Windows. Optional project support is available through Buy Me a Coffee, but there is no paywall or demo mode.

- Download: https://opsroom.live
- Discord: https://discord.gg/Dv6fNAjhAt
