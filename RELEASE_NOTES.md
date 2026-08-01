# OPS ROOM 0.25.50

OPS ROOM 0.25.50 is a public maintenance release that refines the surface of the application without changing how flights are recorded or replayed.

## 0.25.50: Polish Pass

Highlights in this build:

- Status Board advisories now route through a single friendly-error filter so raw application exceptions never appear on the operational dashboard. Unusual conditions surface as operational copy or are journaled to developer diagnostics.
- A global :focus-visible outline rule ships, so keyboard navigation has a consistent visual cue across every module.
- A conservative set of spacing and hierarchy tweaks tightens the breathing room on existing layouts without changing the cockpit-amber visual identity or any module's basic structure.

Behavioural compatibility:

- The ChartFox browser, two-pane chart layout, search-dropdown and ownship overlay behave the same as in the prior release.
- Camera-distance volume remains on by default with the smooth distance blend.
- Black Box recording schema v2 (with the appended first-officer sidestick fields) is unchanged; existing recordings still load and replay normally.
- Public release identity, build channels and acknowledgements stay in sync across the .md and .txt copies.

This build is a stable public release. Refresh the briefing charts, Black Box recordings and Settings pages after upgrading.

## 0.25.50 verified scope

- Public release identity and build channels (Polish Pass, stable).
- Shipped README, release notes and acknowledgements kept in sync across .md and .txt.
- Black Box recording schema unchanged in this release; v2 stays current.
- Procedure charts are still sourced from ChartFox when connected, otherwise SimBrief and AIP/FAA fallbacks remain available.

Aircraft compatibility, simulator fallback behaviour and online network etiquette follow the same conventions as previous public releases.
