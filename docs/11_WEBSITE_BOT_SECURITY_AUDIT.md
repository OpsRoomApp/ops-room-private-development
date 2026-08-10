# 11 — Website & Bot Security / Performance Audit (v0.25.65)

> **Date:** 2026-08-06
> **Scope:** `opsroom-website` + `ops-control-bot` (sibling repos, read-only audit — no code changed)
> **Method:** senior-secops (OWASP Top 10 + secret/supply-chain review), dependency-auditor (CVE check), performance-profiler (hot paths, caching, DB). Verified against actual source, live `npm audit`, git history, and installed package versions.
> **Repo refs:** `github.com/OpsRoomApp/ops-room-website` · `github.com/OpsRoomApp/ops-control-bot` (both `main`)

---

## TL;DR

The architecture is genuinely strong: OAuth allowlist admin auth, token-gated FAA NMS proxy, spoof-proof client-IP trust, parameterized DB code across the admin API, non-root bot container, secrets never found in code or git history.

**However — fix this week:**

1. **[HIGH] SQL injection** in the bot's `/profile-set` command (confirmed, exploitable, ~3-line fix).
2. **[HIGH] Private Freebuff chat DB** (`.freebuff/desktop-v2.db`) committed to the bot's GitHub repo.
3. **[HIGH]** React Router CVE (**GHSA-qwww-vcr4-c8h2**) in both website bundles (low practical impact for a pure SPA, but flagged by `npm audit`).
4. **[MEDIUM-HIGH] Transcript IDOR** — sequential ticket IDs exposed via public, enumerable read/PDF endpoints.

---

## 🔴 HIGH findings

### H1. SQL injection in bot `/profile-set` — confirmed exploitable
**File:** `ops-control-bot/src/bot/cogs/profile.py`

```python
updates.append(f"simulator = '{simulator}'")     # simulator = user-controlled slash option
...
await db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (interaction.user.id,))
```

`simulator`, `network`, and `opsroom_version` are slash-command string options interpolated directly into SQL. Any guild member can run e.g. `/profile-set simulator="x'; DROP TABLE users;--"` and execute arbitrary SQL against the bot's SQLite store (users, tickets, moderation cases, notams, announcements, flight_logs).

**Fix (3 lines):** build `updates` with placeholders and pass values separately:

```python
updates.append("simulator = ?"); values.append(simulator)
...
await db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*values, interaction.user.id))
```

**Verified safe elsewhere:** `admin.py` table list is a hardcoded tuple; `ticket_system.py` `status_col` is a fixed mapping (`"bugs" if is_bug else "tickets"`).

### H2. Private Freebuff chat DB committed to the bot repo
**Files:** `.freebuff/desktop-v2.db`, `.freebuff/desktop-v2.db-shm`, `.freebuff/desktop-v2.db-wal` — **tracked in git** and pushed to `github.com/OpsRoomApp/ops-control-bot`.

Confirmed contents: 4 threads / 22+ messages with real conversation text (thread titles include live agent prompts). This is local Freebuff chat history — treat as sensitive.

**Fix:**
1. `git rm --cached .freebuff/` (keep the files on disk)
2. Add `.freebuff/` to the bot repo's `.gitignore`
3. If the repo is (or may become) public/shared: scrub history with `git filter-repo` and rotate any credentials discussed inside those chats.

### H3. React Router CVE in both website bundles
`react-router-dom@7.18.1` (root + admin) is inside the vulnerable range of **GHSA-qwww-vcr4-c8h2** (React Router RSC-mode CSRF bypass, severity high). Exploitation requires RSC mode / server actions, so practical risk for these client-only SPAs is low — but both `package.json` files should move to a patched release (8.2.1+ or 7.11.x) when convenient. `npm audit` reports 2 high in each package.

### H4. Transcript IDOR — sequential IDs, public read
**Files:** `opsroom-website/admin-api/transcripts.py`

- `POST /api/v1/transcripts/store` — properly gated by bearer `ADMIN_API_TOKEN` ✓
- `GET /api/v1/transcripts/view/{ticket_id}` and `GET /api/v1/transcripts/{ticket_id}/pdf` — **public**, and `ticket_id` is a sequential integer → anyone can enumerate `view/1..N` and read every support-ticket transcript within the 14-day retention (usernames, bug reports, ticket conversations). `int(ticket_id)` prevents path traversal but not enumeration.

**Fix:** serve transcripts via an unguessable share token (random UUID stored with the transcript, or HMAC(`ticket_id`, server secret)), and have the bot's archive links carry that token.

---

## 🟠 MEDIUM findings

| # | Finding | Where | Fix |
|---|---------|-------|-----|
| M1 | No rate limiting on public proxies: `/api/v1/openaip/airspaces`, `/api/v1/notams/*`, `/api/v1/opensky/realworld-search` (OpenAIP/OpenSky are paid-quota upstreams; NMS proxy is token-gated ✓) | `openaip.py`, `notams.py`, `opensky.py` | Per-IP/min limiter on those three routers (reuse the in-memory pattern from `auth.py`) |
| M2 | Appeals endpoint: unauthenticated + unlimited → spam / DB abuse; `int(user_id)` raises unhandled `ValueError` → 500 on non-numeric input | `appeals.py` | Rate-limit by IP, wrap `int()` in try/except, cap statement length |
| M3 | No CSP or HSTS headers (X-Frame-Options, nosniff, Referrer-Policy present ✓) | `nginx.conf` | Add `Content-Security-Policy` (at least admin) + `Strict-Transport-Security: max-age=31536000; includeSubDomains` |
| M4 | Unpinned Python deps in both repos (`fastapi>=`, `discord.py>=`, `aiohttp>=`, `Pillow>=` …), no lockfile/hashes → non-reproducible builds, supply-chain drift | both `requirements.txt` + Dockerfiles | Pin exact versions, `--require-hashes` in Docker, Dependabot + pip-audit in CI. Installed today: aiohttp 3.14.3, discord.py 2.7.1, Pillow 12.3.0 — all current, no known CVEs |
| M5 | admin-api container runs as root (no `USER`) | `admin-api/Dockerfile` | Non-root user, mirroring the bot's Dockerfile |
| M6 | Discord bot token in local `.env` — **untracked and absent from git history (verified)**; keep it that way | bot | gitleaks pre-commit + CI on both repos; rotate if it ever touches a shared surface |
| M7 | Timing-unsafe token compare in transcript `/store` (`auth != expected`) | `transcripts.py` | `hmac.compare_digest()` |

---

## 🟡 LOW / hygiene

- **Committed `__pycache__/*.pyc` (20 files)** in `opsroom-website` — `git rm -r --cached admin-api/__pycache__`, add `__pycache__/` to the website `.gitignore` (bot already ignores it).
- **Empty `.env` directory** at the website root (accidental `mkdir`) — delete; confusing next to `.env.example`.
- **Bot role panel assigns roles by name** (`discord.utils.get(guild.roles, name=label)` in `roles_cog.py`) — labels are hardcoded today, but map to role IDs to survive renames of privileged roles.
- **No command cooldowns** on public bot commands (weather / notam / randomroute hit external APIs) — add `@app_commands.checks.cooldown`.
- **`gcm-diagnose.log`** in the website repo contains email + git-config paths (untracked) — delete / keep out of any commit.
- **`JWT_SECRET` empty → 500** (fails closed ✓) — add a startup guard so a misconfigured deploy fails loudly, and document the `ANALYTICS_SALT` → `"change-me"` analytics-disable behavior.
- **Placeholder `GITHUB_CLIENT_SECRET=your_client_secret` in git history** — run `gitleaks` once per repo to confirm no real secret ever landed there.

---

## ⚡ Performance

### Website — mostly excellent
- Static assets: `Cache-Control: public, immutable` + `expires 6M` on content-hashed Vite output — correct. gzip on (add brotli for ~15–20% more).
- NOTAM SQLite: **indexes present** on `icao_location`, `last_updated`, and `(lat, lon)`; WAL + `busy_timeout` set; 3-min incremental ingest is bounded and separate from serving.
- NMS 60s / OpenAIP 1h in-memory caches — right call.
- Single uvicorn worker — fine at current load; scale with `--workers` later (in-memory caches become per-worker — acceptable duplication, or move to Redis).
- Vite default bundling is fine for the marketing site; admin SPA could add route-level `React.lazy` as pages grow.

### Bot
- aiosqlite single connection + WAL + `busy_timeout=5000` — solid at this scale; shared bot-DB with admin-api handled correctly via WAL on both sides.
- Welcome-image PNG generation is disk-cached under `assets/generated` ✓.
- Main perf lever = cooldowns on external-API commands + pinned deps. No hot-path issues.

---

## ✅ What's done right (verified)

- **nginx `real_ip` trust model** — Cloudflare ranges only; `CF-Connecting-IP` cleared before proxying; `clientip.py` prefers nginx-set `X-Real-IP`; no header-forged rate-limit bypass.
- **Admin auth chain** — OAuth state-CSRF cookie, DB-backed staff allowlist ("table exists ⇒ table is source of truth, no env fallback"), JWT fail-closed, rate-limited login, audit logs.
- **NMS proxy is not an open relay** — 401 without shared bearer token; FAA creds server-side only.
- **Release uploads** — auth-gated, strict `FILENAME_RE`, streamed size enforcement, staged-then-published flow.
- **Bot access control** — moderation via `is_staff`, owner commands via `require_owner`, purge role-guarded, `pending_actions` allowlist-only, sanitized filenames, no `eval/exec/subprocess`, non-root Docker, tokens over HTTPS only and never logged.
- **Secrets** — no real keys in code or history; only untracked local `.env`.

---

## Fix strategy (priority order)

### P0 — this week
| Task | Repo | Est. |
|------|------|------|
| Parameterize `/profile-set` SQL (H1) | bot | 15 min |
| Untrack `.freebuff/` + gitignore; plan history scrub (H2) | bot | 15 min |
| Bump `react-router-dom` to patched release in root + admin (H3) | website | 30 min |

### P1 — next sprint
| Task | Repo | Est. |
|------|------|------|
| Transcript share-token scheme (H4) + keep bot links working | website + bot | 1–2 h |
| Per-IP rate limits on public routers (M1) | website | 1 h |
| Appeals hardening: rate limit + `int()` guard + length cap (M2) | website | 30 min |
| CSP + HSTS headers in nginx (M3) | website | 30 min |
| Pin Python deps + `--require-hashes` (M4) | both | 1 h |
| Non-root admin-api container (M5) | website | 30 min |
| `hmac.compare_digest` for transcript store (M7) | website | 10 min |

### P2 — backlog
- gitleaks pre-commit + CI on both repos (M6 policy)
- Cooldowns on public bot commands
- Role-ID mapping in `roles_cog`
- `__pycache__` + `.env` dir + `gcm-diagnose.log` cleanup
- Startup guard for `JWT_SECRET`; document `ANALYTICS_SALT` behavior
- One-time `gitleaks` history scan on both repos
- (Optional) brotli in nginx; `--workers` when load grows; admin route-level code splitting

### Verification after fixes
1. Re-run the injection payload against `/profile-set` — must be inert (parameterized).
2. `git ls-files | grep freebuff` → empty; `.gitignore` updated.
3. `npm audit --audit-level=high` → 0 in root + admin.
4. Transcript URLs with token: `view`/`pdf` work from the bot's share link, direct numeric-ID requests → 404.
5. `curl -sI https://opsroom.live | grep -i 'strict-transport\\|content-security'` → present.
