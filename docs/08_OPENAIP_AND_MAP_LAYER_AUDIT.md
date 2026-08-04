# OPS ROOM — OpenAIP and Map-Layer Audit

**Version reviewed:** v0.25.61  
**Audit date:** 2026-08-04  
**Scope:** OpenAIP capabilities, current OpenAIP integration status, and the OPS ROOM live-map data pipeline

---

## 1. Executive summary

OpenAIP is a community-maintained worldwide aviation database with APIs, downloadable data, and aviation vector-tile services. It can provide useful supplementary aviation visualization data, especially airspace polygons and metadata, navaids, waypoints, airports, and other general-aviation objects.

OPS ROOM currently contains OpenAIP configuration and future-integration scaffolding, but the code trace found no active OpenAIP API or tile request. The current map is assembled from separate providers and local databases:

- Protomaps/OpenStreetMap for the geographic base map
- VATSIM for live traffic and controllers
- VATSpy/VATSIM boundary data for controller sectors
- OPS ROOM's built-in aviation SQLite database for airports, navaids, waypoints, airways, and simplified airspaces
- Local simulator navigation data for detailed airport surfaces
- AviationWeather.gov and related sources for weather
- FAA NMS for NOTAMs and TFR/FDC data
- SimBrief for flight-plan route data
- ChartFox for charts

The most promising future OpenAIP use is to supplement or replace the current simplified airspace layer with cached, source-labelled OpenAIP airspace polygons and metadata. This should be preceded by a read-only coverage and freshness comparison against the local aviation database.

No application code was modified during the audit. This document is the requested saved record of the audit.

---

## 2. Official OpenAIP sources

- OpenAIP home: <https://www.openaip.net/>
- OpenAIP API documentation: <https://docs.openaip.net/>
- OpenAIP GitHub/developer resources: linked from the official OpenAIP site

The official OpenAIP site describes the platform as a precise worldwide aeronautical database based on contributions from a community of general-aviation enthusiasts. It advertises developer APIs, interactive maps, downloadable data, and real-time data streaming to devices.

---

## 3. What OpenAIP provides

OpenAIP's useful data categories include:

- Airports and aerodromes
- Airspace boundaries
- Airspace classes and types
- Upper and lower altitude limits
- Frequencies and controlling stations
- Navaids
- Waypoints and reporting points
- Aviation-related geographic objects
- Downloadable aviation datasets
- REST/JSON API access
- Aviation vector tiles, including MVT/TMS-style map services
- Data exports such as GeoJSON/OpenAIR-style formats

Potentially relevant airspace types include controlled and special-use areas such as CTR, TMA, CTA, FIR, ATZ, RMZ, TMZ, TSA, restricted/prohibited areas, warning areas, and related classifications. The exact object fields and availability depend on the API/data product and region.

OpenAIP data is primarily useful for aviation visualization, planning support, and general-aviation situational awareness.

### Important operational limitation

OpenAIP is community-contributed data. It should be treated as a useful planning and visualization source—not as the authoritative replacement for:

- FAA NOTAMs
- Official FAA airspace data
- Official regulatory publications
- Certified navigation data
- Official approach/procedure charts

Any OPS ROOM presentation should label OpenAIP-derived objects with their source and freshness where operational decisions could be affected.

---

## 4. APIs, tiles, authentication, and rate limits

The official API documentation describes developer access to OpenAIP services, including structured API data and map-tile services.

### API and tile capabilities

OpenAIP exposes API services for consuming aviation data programmatically. The documentation includes tile-service documentation for vector/map tile consumption, including MVT/TMS-style integrations.

This makes two integration styles possible:

1. **Object API integration**
   - Fetch airports, airspaces, navaids, waypoints, and metadata as structured JSON.
   - Filter, cache, compare, and render objects in the OPS ROOM frontend.

2. **Vector-tile integration**
   - Request map tiles for the current map viewport.
   - Render OpenAIP's aviation overlay through OpenLayers.
   - Avoid shipping a large complete dataset to the browser.

### Authentication

OpenAIP API access requires an OpenAIP account/API key. The key should be treated as a server-side credential and should not be embedded in a distributable desktop application.

### Rate limits and caching

OpenAIP services enforce request limits. Exceeding service limits can result in HTTP `429 Too Many Requests` responses. OpenAIP recommends that clients cache responses locally to reduce repeated requests and avoid rate-limit pressure.

A production integration should therefore include:

- Server-side caching
- Viewport/coordinate normalization
- Request coalescing
- Backoff for 429 responses
- A provider health/status endpoint
- A defined stale-cache policy
- A clear offline/fallback behavior

---

## 5. Licensing and redistribution

The official OpenAIP site states that OpenAIP data is licensed under **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**.

The site describes the license as allowing third parties to:

- Share OpenAIP data in different formats or media
- Remix, transform, and build upon the data
- Include OpenAIP data in paid or commercial applications, provided the data itself is not exclusively sold as a standalone data product

Before shipping a production integration, OPS ROOM should still confirm:

- Required attribution wording and placement
- Whether the selected API/tile service has additional terms
- Whether persistent local caching or redistribution is permitted for the specific endpoint
- Whether commercial use of a particular service requires separate permission
- How transformed or merged data must be attributed

OpenAIP should not be presented as an official FAA source merely because it is displayed alongside FAA data.

---

## 6. Is OPS ROOM currently using OpenAIP?

Based on the code trace, **no active OpenAIP API or tile request is currently being made**.

There is OpenAIP scaffolding, but it is effectively dormant.

### Existing OpenAIP configuration

`app/settings_store.py:78–79` defines:

```python
"openaip_map_enabled": True,
"openaip_api_key": "",
```

The Host settings page allows the user to enter an OpenAIP key:

- `app/static/host.html:139–142`
- `app/static/host.js:132`
- `app/static/host.js:150`

The setting is stored as a user integration setting.

### Existing OpenAIP helper

`app/charts.py:1579–1582` contains an `openaip_key()` helper that resolves a user-configured value and has an embedded fallback.

The code search found no active network caller that uses this helper to make an OpenAIP request.

### Existing OpenAIP status output

`app/map_data.py:274` reports configuration metadata similar to:

```python
"openaip": {
    "configured": bool(settings.get("integrations", {}).get("openaip_api_key")),
    "role": "metadata/vector overlay provider",
    "enabled": bool(settings.get("integrations", {}).get("openaip_map_enabled", True)),
}
```

This reports configuration status only. It does not fetch OpenAIP data.

### Misleading chart function name

The frontend function `openAipChart()` at `app/static/opsroom.js:2701` loads a supplied chart URL into the chart viewer. It is not an OpenAIP API client and does not demonstrate that the application is contacting OpenAIP.

### Current conclusion

The embedded OpenAIP key is currently unused future scaffolding. Removing it should not disable the current live map, traffic, weather, FAA NOTAM, ChartFox, or airport-surface functionality, based on the traced call paths.

---

## 7. Current OPS ROOM map architecture

The map is rendered with OpenLayers in `app/static/opsroom.js`.

The main live-map payload is produced by `app/map_data.py:build_live_map()` and exposed by:

- REST: `/api/map/live`, implemented at `app/main.py:1271–1276`
- WebSocket: `/ws/map`, implemented at `app/main.py:1279–1295`

The frontend creates independent OpenLayers layers for the basemap, aviation objects, live traffic, controllers, coverage, route, NOTAMs, and airport surface.

---

## 8. How the current map layers are generated

### 8.1 Geographic base map

#### Raster fallback

`app/static/opsroom.js:4390` creates an OpenStreetMap raster layer using OpenLayers:

```javascript
new ol.source.OSM(...)
```

This is the fallback/background map.

#### Main vector basemap

`app/static/opsroom.js:4393` creates the primary vector-tile layer:

```javascript
url: '/api/map/tile/{z}/{x}/{y}.mvt'
```

The endpoint is implemented at:

- `app/main.py:1212–1222`
- `app/map_tiles.py`

`app/map_tiles.py` requests:

```text
https://api.protomaps.com/tiles/v4/{z}/{x}/{y}.mvt
```

The returned tiles are cached locally for up to seven days.

Therefore, the current general geographic map comes from **Protomaps/OpenStreetMap**, not OpenAIP.

---

### 8.2 Live aircraft traffic and controllers

The backend fetches VATSIM data through `app/vatsim_client.py`:

```text
https://data.vatsim.net/v3/vatsim-data.json
```

The live map pipeline produces:

- Aircraft positions
- Callsigns
- Altitude
- Groundspeed
- Heading
- Origin and destination
- Online controllers
- Controller frequencies
- ATIS information
- Ownship-relative distance where local telemetry is available

The frontend renders these as OpenLayers vector features in separate aircraft, ownship, and controller layers.

This is live VATSIM data and is unrelated to OpenAIP.

---

### 8.3 ATC sector coverage

For center/FSS controllers, OPS ROOM loads VATSpy boundary data from:

```text
https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/Boundaries.geojson
```

through `app/vatspy_boundaries.py`.

If a matching sector polygon is found, OPS ROOM renders the original GeoJSON geometry.

If no sector polygon is found, OPS ROOM creates an estimated coverage circle using controller facility and visual-range data.

The current coverage model is therefore:

```text
VATSpy polygon when available
        otherwise
estimated radius circle
```

OpenAIP airspace data would be a different aviation overlay and should not be confused with VATSIM controller-sector coverage.

---

### 8.4 Airports

Airports primarily come from the built-in OPS ROOM aviation SQLite database:

```text
app/data/navigation/opsroom_aviation.sqlite
```

The implementation is in `app/aviation_data.py`.

The backend exposes:

```text
/api/livemap/layers/airports
```

implemented at `app/main.py:1247–1250`.

The frontend requests airports using the current map bounding box and converts them into OpenLayers point features.

Route and nearby airports are additionally derived from:

- SimBrief route data
- Ownship position
- Nearest-airport calculations
- The built-in airport database

OpenAIP could supplement airport metadata, but it should not silently override local or official operational data.

---

### 8.5 Navaids

Navaids come from the built-in aviation database.

Endpoint:

```text
/api/livemap/layers/navaids
```

Implementation:

```text
aviation_data.navaids_layer()
```

The returned data includes fields such as:

- Identifier
- Name
- Type
- Frequency
- Latitude/longitude
- Range
- Elevation

This is a potential area where OpenAIP could provide supplemental or comparison data.

---

### 8.6 Waypoints

Waypoints are loaded from:

```text
/api/livemap/layers/waypoints
```

They are queried from the built-in `nav_waypoint` table using the current map bounding box.

OpenAIP could provide additional general-aviation waypoints or help fill regional coverage gaps, subject to data-quality and licensing review.

---

### 8.7 Airways

Airways are loaded from:

```text
/api/livemap/layers/airways
```

They come from the built-in `nav_airway` table.

The backend returns line endpoints and altitude limits, which the frontend renders as airway lines.

OpenAIP is not currently used for this layer.

---

### 8.8 Airspaces

Airspaces are loaded from:

```text
/api/livemap/layers/airspaces
```

They come from the built-in `nav_boundary` table.

The current backend returns fields such as:

- Name
- Type
- Minimum altitude
- Maximum altitude
- Minimum/maximum latitude
- Minimum/maximum longitude

This appears to be a simplified local airspace representation. The data model shown in `aviation_data.py` uses bounding fields rather than returning full polygon geometry in this layer response.

This is the strongest candidate for OpenAIP enhancement if richer actual airspace geometry and metadata are desired.

The codebase should be audited further to establish:

1. Where the built-in aviation database originally came from.
2. How frequently it is updated.
3. Whether its airspace data is polygon-based internally or only represented by bounding boxes at the API boundary.
4. Whether it provides adequate coverage outside the main operating regions.
5. Whether current altitude/reference semantics are sufficient for display.

---

### 8.9 Airport runway and taxiway surface

When the map is zoomed into an airport, OPS ROOM calls:

```text
/api/livemap/airport-surface?icao=XXXX
```

The source is normally a locally detected simulator navigation database, such as the Little Navmap/MSFS database.

The backend loads:

- Runways
- Runway ends
- Taxiway segments
- Taxiway labels
- Starts
- Parking data for stand detection

`app/aviation_data.py` merges small taxiway segments into longer polylines before sending them to the browser.

This is not OpenAIP data. It is local simulator-specific data and is more appropriate for detailed airport-surface rendering than a general global aviation database.

---

### 8.10 Weather

Weather is fetched through `app/weather_client.py`, including AviationWeather.gov endpoints and related ATIS processing.

The briefing/map weather pipeline uses:

- METAR
- Wind
- Visibility
- Temperature/dew point
- QNH/altimeter
- Flight category
- Real ATIS where available
- METAR-derived fallback text where real D-ATIS is unavailable

OpenAIP would not replace this weather pipeline.

---

### 8.11 NOTAMs

The FAA NMS integration is separate from OpenAIP.

The desktop uses `nms_client.py` and related briefing/map code for:

- NOTAMs by location
- Geo-radius NOTAM searches
- Individual NOTAM lookup
- Text search
- TFR/FDC filtering
- Route-related NOTAM enrichment
- Live critical-area notifications around the aircraft

OpenAIP should not be used as the authoritative source for FAA NOTAMs.

---

### 8.12 Flight route and ownship

The route is derived from the cached SimBrief flight plan and local simulator telemetry.

The map payload includes:

- Origin
- Destination
- Alternate
- Route points
- Ownship location
- Ownship altitude, heading, track, and groundspeed
- Nearest airport
- Route-staleness indication

This is local/SimBrief/VATSIM data and is unrelated to OpenAIP.

---

## 9. Where OpenAIP could add value

### 9.1 Actual airspace polygons

This is the strongest candidate.

OpenAIP could provide:

- Actual airspace geometry
- Airspace class
- Airspace type
- Vertical limits
- Frequencies
- Names and identifiers
- Activation or status metadata where available

That could improve the current simplified airspace display, particularly for visual context and general-aviation use.

### 9.2 Better aviation object coverage

OpenAIP could supplement or validate:

- Navaids
- VORs/NDBs
- Waypoints
- Reporting points
- Airports
- Airspace metadata

### 9.3 OpenAIP vector-tile overlay

Instead of downloading every object and rendering it manually, OPS ROOM could potentially use OpenAIP aviation vector tiles as a separate overlay.

This would be an optional map layer, not a replacement for the Protomaps geographic basemap.

### 9.4 Data quality comparison

OpenAIP could be used in a read-only comparison tool to measure:

- Coverage
- Freshness
- Polygon quality
- Altitude metadata
- Frequency completeness
- Duplicate rate
- Regional accuracy
- Differences from the local aviation database

This would provide evidence before committing to a production integration.

---

## 10. What OpenAIP should not replace

OpenAIP should not replace:

1. FAA NOTAMs or TFR data.
2. Live VATSIM traffic or controller data.
3. AviationWeather.gov weather data.
4. Detailed simulator airport surfaces.
5. Official approach charts.
6. Certified or regulated navigation data.
7. The Protomaps/OpenStreetMap geographic basemap.
8. Official FAA or national aviation-authority sources where authoritative information is required.

---

## 11. Recommended future proxy architecture

If OpenAIP is adopted, the recommended flow is:

```text
OPS ROOM desktop
        |
        | authenticated request to OPS ROOM proxy
        v
admin.opsroom.live
        |
        | server-side OpenAIP API key
        v
OpenAIP API / Tiles API
```

### Server-side configuration

Use a dedicated server-side configuration such as:

```env
OPENAIP_API_KEY=<server-side-key>
OPENAIP_ENABLED=true
```

If the desktop must authenticate to the proxy, use a separate credential:

```env
OPENAIP_PROXY_TOKEN=<separate-internal-token>
```

Do not reuse:

- `ADMIN_API_TOKEN`
- FAA NMS credentials
- Discord bot tokens
- JWT signing secrets
- OpenSky credentials

### Proxy responsibilities

The proxy should provide:

- Fixed OpenAIP upstream allowlisting
- Server-side API-key injection
- Endpoint and parameter validation
- Bounded viewport/bbox limits
- Response caching
- 429/backoff handling
- Provider status reporting
- Source/freshness metadata
- Attribution metadata
- No arbitrary outbound URL forwarding
- Authentication/rate limiting appropriate to the desktop clients

The desktop should receive aviation data or tiles, never the upstream OpenAIP key.

---

## 12. Recommended product decision

Do not add OpenAIP merely because an embedded key or settings field already exists.

The current map already uses a sensible set of specialized sources. OpenAIP is useful only if it fills a measurable gap.

### Recommended priority

1. Build a read-only coverage comparison between the local aviation database and OpenAIP.
2. Focus the comparison initially on airspace polygons, airspace metadata, and navaids.
3. Measure freshness and regional completeness.
4. Confirm licensing/attribution requirements for the selected API/tile endpoints.
5. Decide whether the result warrants a server-side proxy and a new optional map layer.

### Best likely enhancement

> Replace or supplement the current simplified airspace layer with cached OpenAIP airspace polygons, displayed with clear source and freshness labels.

### Overall assessment

OpenAIP is **useful but not urgent** for the current OPS ROOM product. FAA NMS, VATSIM, airport-surface rendering, ChartFox, weather, and Protomaps are more directly connected to the current workflow.

OpenAIP becomes strategically valuable if OPS ROOM wants:

- Richer VFR/general-aviation context
- Better airspace visualization
- A global aviation overlay
- Cross-checking of local reference data
- A future server-side aviation-data service

---

## 13. Audit evidence index

| Area | Evidence |
|---|---|
| OpenAIP settings | `app/settings_store.py:78–79`, `app/settings_store.py:258–259` |
| OpenAIP Host UI | `app/static/host.html:139–142`, `app/static/host.js:132`, `app/static/host.js:150` |
| OpenAIP helper | `app/charts.py:1579–1582` |
| OpenAIP status metadata | `app/map_data.py:274` |
| OpenAIP-named chart viewer | `app/static/opsroom.js:2701` |
| Protomaps tile provider | `app/map_tiles.py` |
| Protomaps tile endpoint | `app/main.py:1207–1222` |
| OpenLayers map setup | `app/static/opsroom.js:4389–4410` |
| Live map REST/WebSocket | `app/main.py:1271–1295` |
| Live map data assembly | `app/map_data.py:build_live_map()` |
| VATSIM feed | `app/vatsim_client.py` |
| VATSpy boundaries | `app/vatspy_boundaries.py` |
| Local aviation layers | `app/aviation_data.py:166–276` |
| Local airport surface | `app/aviation_data.py:369–465` |
| Local layer routes | `app/main.py:1247–1269` |
| Frontend layer fetches | `app/static/opsroom.js:4217–4241` |
| Airport surface fetch | `app/static/opsroom.js:4348–4378` |
| Weather | `app/weather_client.py` |
| FAA NMS client | `app/nms_client.py` and `app/main.py:923–1048` |

---

## 14. Final conclusion

OpenAIP provides real value as a supplementary aviation-data source, especially for airspace polygons and general-aviation metadata. OPS ROOM does not currently consume OpenAIP despite having dormant configuration scaffolding and an embedded fallback key.

The current map layers are generated through a deliberate combination of Protomaps/OpenStreetMap, VATSIM, VATSpy, local aviation SQLite data, local simulator navigation data, SimBrief, FAA NMS, and weather services.

The correct next step is not immediate integration. It is a read-only comparison of OpenAIP against the local aviation data, followed by a server-side proxy only if the comparison demonstrates a clear product benefit.
