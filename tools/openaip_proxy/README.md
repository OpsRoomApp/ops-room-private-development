# OPS ROOM — OpenAIP proxy

Keeps your OpenAIP API key **server-side** on the VPS — exactly like the OpenSky
proxy (`admin.opsroom.live/api/v1/realworld-search`). The desktop app calls this
proxy instead of OpenAIP directly, so users never need (or see) an OpenAIP key,
and no user configuration is required.

> **Production path:** this endpoint is now **part of the website backend**
> (`opsroom-website/admin-api/openaip.py`, served at
> `https://opsroom.live/api/v1/openaip/airspaces` — same FastAPI app as the FAA
> NMS proxy). This folder is the standalone/dev reference implementation and
> the standalone deployment option. The desktop's baked-in default URL points
> at the website endpoint.

## Why

- Your OpenAIP key is never embedded in the distributed desktop build.
- One key serves every installation; rate limits are centralized and cached.
- The proxy is the only component allowed to talk to OpenAIP (allowlist model).
- The endpoint is public HTTPS (like realworld-search); a token is optional.

## Contract (must match `app/openaip_client.py`)

```
GET /openaip/airspaces?bbox=<west,south,east,north>&limit=<n>
Header: x-opsroom-proxy-token: <OPENAIP_PROXY_TOKEN>   (optional)
```

- `bbox` — 4 comma-separated lon/lat values, span capped at 40° lon / 24° lat.
- `limit` — optional, capped at 1200.
- Response — the OpenAIP payload passed through unchanged (GeoJSON
  FeatureCollection or legacy JSON), so the desktop parser is identical for
  proxy and direct sources.
- `GET /healthz` — liveness/diagnostic endpoint (no token required; reports
  only booleans, never secrets).

## Environment

| Variable             | Required | Meaning                                                     |
|----------------------|----------|-------------------------------------------------------------|
| `OPENAIP_API_KEY`    | yes      | Your server-side OpenAIP API key                           |
| `OPENAIP_PROXY_TOKEN`| no       | When set, the desktop must present it; when unset the       |
|                      |          | endpoint is public HTTPS (same as realworld-search)         |
| `OPENAIP_CACHE_DIR`  | no       | Disk cache dir (default `./cache`)                         |
| `OPENAIP_CACHE_TTL`  | no       | Cache seconds (default `3600`)                             |
| `HOST` / `PORT`      | no       | Bind (default `0.0.0.0:8000`)                              |

## Deploy

```bash
cd tools/openaip_proxy
pip install -r requirements.txt
export OPENAIP_API_KEY="your-openaip-key"
# optional: export OPENAIP_PROXY_TOKEN="$(openssl rand -hex 24)"
uvicorn main:app --host 0.0.0.0 --port 8000
```

Put it behind TLS (Caddy/nginx reverse proxy).

## Wiring the desktop to the proxy

**Nothing to configure.** The desktop ships with the default endpoint baked in
(`https://admin.opsroom.live/api/v1/openaip/airspaces`), mirroring how
`OPSROOM_VPS_URL` defaults to the OpenSky proxy. It just works.

Optional overrides (only needed if you change the server address or add a token):

1. **Managed build**: add to your private keys file
   `E:\Ops Room Project\private_keys\opsroom_api_keys.local.json`:

   ```json
   {
     "openaip_proxy_url": "https://admin.opsroom.live/api/v1/openaip/airspaces",
     "openaip_proxy_token": "<optional token>"
   }
   ```

   `tools/inject_managed_keys.py` injects `openaip_proxy_url` /
   `openaip_proxy_token` into `app/managed_keys.py` at build time.

2. **Environment override** (private validation): `OPENAIP_PROXY_URL` and
   `OPENAIP_PROXY_TOKEN`.

3. **User settings**: `integrations.openaip_proxy_url` / `openaip_proxy_token`.

Resolution order: settings → environment → managed build secrets → baked-in
default URL. The desktop calls the proxy first; if the proxy is unreachable it
falls back to a direct OpenAIP call only when a key is embedded, and finally to
the built-in local aviation DB. The map layer never breaks.

## Security notes

- The token (if used) is compared with a constant-time compare; never logged.
- No arbitrary URL forwarding — only the fixed OpenAIP endpoints are reachable.
- bbox size/range is validated before hitting the upstream.
- Upstream 429s are retried once with backoff; responses are cached.
- `/healthz` returns booleans only — no keys, no tokens.
