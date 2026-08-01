# OPS ROOM — Security & Secrets Management

**Version:** v0.25.48
**Last Updated:** 2026-07-31

---

## Principle: Zero Plain-Text Secrets in Source Code

No credentials, API keys, or secrets of any kind are embedded as plain-text fallback strings in any Python, JavaScript, or configuration file across either repository. Every credential is loaded strictly from environment variables at runtime.

---

## Credential Isolation Matrix

| Credential | Where It Lives | How It's Accessed | Visible To Desktop App? |
|---|---|---|---|
| `OPENSKY_CLIENT_ID` | `.env` on VPS | `os.environ.get("OPENSKY_CLIENT_ID", "")` in `opensky.py` | **No** — only the website proxy handles this |
| `OPENSKY_CLIENT_SECRET` | `.env` on VPS | `os.environ.get("OPENSKY_CLIENT_SECRET", "")` in `opensky.py` | **No** |
| `GITHUB_CLIENT_ID` | `.env` on VPS | Admin panel OAuth config | **No** |
| `GITHUB_CLIENT_SECRET` | `.env` on VPS | Admin panel OAuth config | **No** |
| `JWT_SECRET` | `.env` on VPS | Admin panel session tokens | **No** |
| ChartFox OAuth token | Desktop app data dir | OAuth2 flow; stored in `settings.json` | **Yes** — user-scoped, revocable |
| ChartFox client ID | `app/charts.py` | Public identifier (`019f9162-...`), not a secret | **Yes** — public by design |
| ChartFox client secret | Exchanged server-side | Never stored by desktop app | **No** |
| Lido API key | Injected at build time | `BUILD OPS ROOM COMPLETE.bat` | **Yes** — managed, not user-facing |

---

## OAuth2 Flows

### ChartFox (Desktop App)

The desktop app uses the **OAuth2 Authorization Code** flow with a loopback redirect:

1. User triggers OAuth from the Charts module
2. Browser opens `https://api.chartfox.org/oauth/authorize?...`
3. User authenticates on ChartFox.org
4. ChartFox redirects to `http://localhost:8080/api/charts/chartfox/callback?code=...`
5. Backend exchanges the code for a Bearer token at `https://api.chartfox.org/oauth/token`
6. Token is stored in the app's local data directory (not in source code)
7. Token is user-scoped, short-lived (auth failures yield clear reconnect prompts)

**The OAuth client secret is never stored by the desktop app** — it's only used in the server-side code exchange step.

### OpenSky Network (Website Proxy)

The website proxy uses the **OAuth2 Client Credentials** flow:

1. Proxy requests a token from `https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token`
2. `grant_type=client_credentials` with `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET`
3. Token is used in `Authorization: Bearer <token>` for all OpenSky API calls
4. Token is short-lived and re-fetched on expiry
5. The desktop app **never** sees, stores, or handles these credentials

---

## Proxy Layer Architecture

```
┌─────────────────────┐
│   Desktop App        │  Public HTTPS (no auth)
│   (opsroom-app)      │  GET /api/v1/realworld-search?callsign=DLH400&origin=EDDF
└────────┬────────────┘
         │  ← No credentials needed
         ▼
┌─────────────────────┐
│   Website Proxy      │  OAuth2 Bearer token
│   (opsroom-website)  │  Authorization: Bearer <token>
│   admin.opsroom.live │
└────────┬────────────┘
         │  ← OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET (from .env)
         ▼
┌─────────────────────┐
│   OpenSky Network    │
│   opensky-network.org│
└─────────────────────┘
```

### Why This Matters

- The desktop app ships as a compiled executable to end users. Any credential embedded in the binary could be extracted.
- By keeping all OpenSky credentials on the website VPS, the desktop app has **zero secrets to leak**.
- The proxy endpoint is intentionally public — rate-limiting and caching provide protection without requiring per-user auth.

---

## Environment Variable Configuration

### Desktop App

The desktop app requires **no sensitive environment variables** to function:

| Variable | Purpose | Required? |
|---|---|---|
| `OPSROOM_VPS_URL` | Override the OpenSky proxy URL | No (uses default) |

The `OPSROOM_VPS_USER` and `OPSROOM_VPS_PASS` variables **do not exist** — they were removed in the security cleanup and have no effect if set.

### Website Proxy

The website proxy requires two environment variables, configured in `.env` and `docker-compose.yml`:

```bash
# .env (on VPS only — never committed to source control)
OPENSKY_CLIENT_ID=your-client-id
OPENSKY_CLIENT_SECRET=your-client-secret
```

```yaml
# docker-compose.yml (environment block)
services:
  admin-api:
    environment:
      - OPENSKY_CLIENT_ID=${OPENSKY_CLIENT_ID}
      - OPENSKY_CLIENT_SECRET=${OPENSKY_CLIENT_SECRET}
```

**Startup validation:** If either variable is empty at startup, a warning is logged:

```
WARNING: OpenSky credentials not configured — set OPENSKY_CLIENT_ID and
OPENSKY_CLIENT_SECRET in the environment. Real-world flight search will
return 502 until credentials are provided.
```

---

## `.gitignore` Rules

Both repositories enforce that sensitive files are never committed:

```gitignore
# opsroom-website
.env
.env.local
.env.production

# opsroom-app
.env
*.key
*.pem
```

---

## Audit Checklist

Before any public release, verify:

- [ ] `grep -r "badgujarnishant"` returns zero matches in source code
- [ ] `grep -r "HQbVw1jn"` returns zero matches in source code
- [ ] `grep -r "OPSROOM_VPS_USER\|OPSROOM_VPS_PASS"` returns zero matches in source code
- [ ] `.env.example` contains `OPENSKY_CLIENT_ID=` and `OPENSKY_CLIENT_SECRET=` with **empty values**
- [ ] `docker-compose.yml` has the `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` environment block
- [ ] No Python, JavaScript, or batch file contains a hardcoded credential string
- [ ] Build script does not inject or package any VPS admin credentials
