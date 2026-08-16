# OPS ROOM — Complete Growth Master Plan

**Status:** v2.0 — supersedes the earlier `13_GO_TO_MARKET_STRATEGY.md`
**Owner:** exzonom (founder)
**Prepared:** 2026-08-15, aligned to the v0.25.0 public release
**Scope:** userbase growth, SEO, marketing, and concrete improvements to all three
repos (desktop app, Discord bot, website).
**Confidence tags:** 🟢 verified · 🟡 estimated · 🔴 assumed.

---

# PART A — FOUNDATION

## 1. Executive summary

OPS ROOM is not competing against another app. It is competing against the habit
of running five separate tools (SimBrief, Navigraph/LittleNavMap, Volanta, Sky
Dolly, GSX). The one product that used to bundle all of this — SimToolkitPro —
has been dormant since ~2022, so the "free all-in-one ops suite" position is
**vacant**. We take it.

The growth plan has four engines, run in this order:

1. **Own the category.** "Cockpit ops suite" — said everywhere, on every listing,
   until the market repeats it back.
2. **Use the in-sim presence as the wedge.** The toolbar tablet (2020 + 2024) and
   the native EFB app (2024) are ours alone. No competitor shows the whole suite
   *inside the cockpit*. Every screenshot is an ad.
3. **Weaponize free.** Volanta gates its best features behind payware; Navigraph is
   a subscription. We give the full suite away during public beta. "Free during
   public beta" is the headline, the CTA, and the honest scarcity.
4. **Turn every download into a distributor** — a review on flightsim.to, a shared
   cockpit screenshot, a Discord invite. Reviews/ratings are the flightsim.to
   ranking engine; we farm them deliberately for the first 30 days.

The single highest-leverage moves in the next 30 days, in order:

1. Fix the website's SEO foundation (missing sitemap, no structured data, no
   prerender, keyword-less titles) — **§12**.
2. Rebuild the flightsim.to listing around the in-sim tablet visual — **§7**.
3. Drive a 20-review wave from Discord + the app + the release bot — **§7.2, §14, §15**.

Everything else compounds on those three.

---

## 2. The market (sized, with sources)

| Signal | Value | Confidence | Source |
|---|---|---|---|
| MSFS 2024 concurrent players (Steam) | ~5,300–6,000 live; ~24.9k all-time peak | 🟢 | SteamDB / steamcharts, Aug 2026 |
| Steam is the minority of the player base | Game Pass + Microsoft Store + Xbox add multiples | 🟡 | Standard MSFS distribution |
| MSFS 2020 still out-draws 2024 on Steam | 2024 declined after launch; 2020 retains more concurrents | 🟢 | Steam Charts + MSFS forums |
| VATSIM active members | **191,316** (Q1 2025), 92% pilots (~176k) | 🟢 | Wikipedia / VATSIM |
| flightsim.to role | Default addon marketplace; "Hot Trending This Week" + "Most popular in 7 days" | 🟢 | flightsim.to |
| MSFS 2024 third-party EFB apps today | Navigraph Charts, SimBrief Dispatch, Bushtalk, Fenix, Carenado — a *short* list | 🟢 | MSFS forums thread |

**What this means:**

- 🟡 Total addressable audience is **hundreds of thousands** of serious MSFS users.
- 🟢 VATSIM's ~176k pilots are the primary beachhead: FIDS, dispatch, Flight Watch
  and Black Box replay are VATSIM-native. Win VATSIM and you win the most
  connected, most talkative segment.
- 🟢 The 2024 EFB app list is short and dominated by paid Navigraph. A **free**
  third-party EFB app that is a *whole ops suite* (not just charts) is genuinely
  newsworthy and list-worthy — this is our SEO and PR wedge.
- 🟢 Both sims matter: the toolbar tablet is the reach play (2020 + 2024), the
  native EFB is the prestige play (2024). Ship and market both.

---

## 3. Competitive intelligence

Threat matrix (competitive-intel):

| Tool | Job | Price | Relationship | Threat |
|---|---|---|---|---|
| **Volanta** | Tracking + logbook + map | Free tier + paid premium | Direct | **HIGH** |
| **Sky Dolly** | Replay (open source) | Free | Direct (Black Box) | MEDIUM |
| **Flight Control Replay** | Replay (paid) | Paid | Direct (replay) | MEDIUM |
| **SimBrief** | Dispatch OFP | Free (Navigraph) | Complementary ally | LOW |
| **Navigraph** | Charts + map + 2024 EFB apps | Paid sub | Adjacent | LOW-MED |
| **LittleNavMap** | Planner/map | Free | Adjacent | LOW |
| **SimToolkitPro** | Free all-in-one | Free | **Direct — dormant since ~2022** | LOW (vacant throne) |
| **GSX** | Ground services | Paid | Complementary | LOW |
| **Neofly / Self-Loading Cargo** | Career/immersion | Free/paid | Different job | LOW |
| **AvioDeck / ElevateX** | Web VATSIM dashboards | Free/paid | Web-only | LOW-MED |

### 3.1 The one to beat: Volanta

Volanta owns the "flight tracker + logbook" habit. The proven attack is price +
completeness, and it already works — the exact YouTube title *"A Volanta Rival for
FREE?"* exists. 🟢

- Volanta's best features are paywalled. We give the whole suite free in beta.
- Volanta is desktop-first. We are **in-sim** (tablet + EFB) *and* desktop *and*
  iPad/browser.
- Do **not** copy Volanta's marketing. Exploit the two things it can't copy:
  in-sim presence and the all-in-one bundle.

### 3.2 Sky Dolly / Flight Control Replay (replay)

- Sky Dolly is free and excellent (4.7, 162 reviews 🟢). Do not fight it on
  "replay" alone. Position Black Box as *in-sim* replay built into the ops
  workflow — one tab of a suite, not a standalone tool.
- The search demand is real: "how to replay MSFS 2020", "best replay tool MSFS
  2024" are active queries. 🟢 A "How to replay MSFS" guide that ends with "or use
  OPS ROOM Black Box, free" captures it.

### 3.3 The vacant throne: SimToolkitPro

SimToolkitPro was exactly our product and stopped shipping around 2022. 🟡 We
inherit its demand: "simtoolkitpro alternative", "volanta alternative free", "best
free flight tracking MSFS". Nobody is defending these. This is the single most
important strategic fact in the document.

### 3.4 Feature-gap matrix

| Capability | OPS ROOM | Volanta | Sky Dolly | SimBrief | Navigraph |
|---|---|---|---|---|---|
| Live OFP dispatch | ✅ | ⚠️ | ❌ | ✅ | ⚠️ |
| Flight Watch / live map | ✅ | ✅ | ❌ | ❌ | ✅ |
| Black Box + **in-sim replay** | ✅ | ⚠️ | ✅ (no in-sim) | ❌ | ❌ |
| RAAS + landing alerts | ✅ | ❌ | ❌ | ❌ | ❌ |
| Performance calculator | ✅ | ❌ | ❌ | ⚠️ | ⚠️ |
| VATSIM FIDS | ✅ | ❌ | ❌ | ❌ | ❌ |
| PIREP + logbook | ✅ | ✅ | ⚠️ | ❌ | ❌ |
| **In-sim toolbar tablet** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Native 2024 EFB app** | ✅ | ❌ | ❌ | ⚠️ | ✅ |
| iPad / browser client | ✅ | ✅ | ❌ | ✅ | ✅ |
| Whole thing free | **Free (beta)** | Paid tiers | Free | Free | Paid |

Every `✅` in the OPS ROOM column against a `❌` elsewhere is a headline. Bundle:
**"Dispatch, Flight Watch, Black Box replay, RAAS, performance and FIDS — one app,
in the cockpit, free."**

---

## 4. Positioning & category design

The four CMO questions, answered:

1. **Who are we for?** The serious MSFS 2020/2024 pilot who flies online
   (VATSIM/IVAO), files realistic flights, and currently runs 3–6 tools.
   Secondary: virtual airlines and streamers who need dispatch + debrief + replay.
2. **Why do they choose us?** One free app replaces the tool stack, and it lives
   *inside the cockpit*. The alternative costs money and still isn't in-sim.
3. **How do they find us?** flightsim.to, YouTube roundups, Google (free
   alternative searches), VATSIM communities, Reddit, Discord, and the in-sim
   tablet itself.
4. **Is it working?** Weekly: flightsim.to downloads + rating count, website
   organic impressions (Search Console), Discord joins, and "how did you find us"
   attribution (§17).

**Positioning statement:**

> OPS ROOM is the all-in-one cockpit ops suite for Microsoft Flight Simulator —
> dispatch, Flight Watch, Black Box replay, RAAS and performance, in one free app
> that runs in the cockpit tablet, on the EFB, and on any screen you own.

**Category name to claim:** "cockpit ops suite." Never "utility" or "companion app."
The word "suite" carries the "replaces five apps" meaning and has near-zero
competition in search.

**Battlecards (one line each):**

- vs Volanta: "Volanta tracks your flight. OPS ROOM runs it — in the cockpit, free."
- vs Sky Dolly: "Sky Dolly replays. OPS ROOM records, replays *in the sim*, and
  feeds the same data to your logbook, PIREP and leaderboard."
- vs SimBrief/Navigraph: "SimBrief and Navigraph plan the flight. OPS ROOM is what
  you run it with — free, and it talks to their OFP."

---

# PART B — ACQUISITION

## 5. Growth model — community-led growth

This is a community-led product. The loop:

```
Cockpit screenshot (in-sim tablet/EFB) → posted to Reddit/Discord/TikTok
  → curious pilot visits flightsim.to → downloads free app → joins Discord
  → review + referral ask → their screenshot/stream → loop
```

Three conversion points, optimized in order:

1. **Impression → listing** (thumbnail + title + trending on flightsim.to).
2. **Listing → download** (rating count, description, free, social proof).
3. **Download → advocate** (review ask + shareable moments + Discord invite).

Paid ads stay off until organic channels are saturated — the audience is small,
ad-averse, and cheaper to reach through reviews (§19 kill criteria). 🔴

---

## 6. Channel strategy — ORB map

A complete plan covers Owned, Rented and Borrowed.

### 6.1 Owned (control — activate first)

| Channel | Action | Why |
|---|---|---|
| opsroom.live | Fix SEO foundation (§12), rebuild hero around in-sim tablet + "free" | Owned conversion surface, no algorithm |
| Discord | Welcome flow asks "how did you find us" + download CTA + review CTA (§14) | Attribution + review engine |
| Release bot | Auto-posts releases; append one-line review ask (§14) | Every release = review drive |
| Email list | Not built yet — capture email at download for release/roundup mail | Owned launch leverage |

### 6.2 Rented (algorithmic — play by their rules)

| Channel | Action | Why |
|---|---|---|
| **flightsim.to** | Rebuild listing, weekly news posts, reply to every comment | #1 rented channel (§7) |
| **Google** | Comparison + guide pages for "free alternative" queries (§12.6) | Highest-intent traffic |
| **YouTube** | 45s hook clip + 2–3 min walkthrough + replay demos | Roundups + search |
| **TikTok / Shorts / Reels** | Tablet reveal, Black Box replay, RAAS callouts | Neofly proved the niche works 🟢 |
| **Reddit** | r/MicrosoftFlightSim + r/flightsim: genuine "I made this" + screenshot | High-trust |
| **X/Twitter** | Devlog threads ("today the EFB app shipped") + screenshot per post | Developer-in-public authority |

### 6.3 Borrowed (other people's audiences — start 2+ weeks early)

| Channel | Action | Why |
|---|---|---|
| **Mid-size YouTubers (10k–100k)** | Outreach via `YOUTUBER_PITCH.md`; early access + ready-to-record setup | "Best free MSFS addons" roundups are the discovery engine |
| **FSElite / flight-sim news** | Pitch the "free in-sim tablet + native EFB + all-in-one" angle | Free link + authority |
| **VATSIM communities / VAs** | "Adopt OPS ROOM as your VA toolkit" pitch to 3–5 VAs | A VA adoption compounds |
| **Newsletter swaps** | Trade mentions with flight-sim newsletters | Borrowed list, near-zero cost |

---

## 7. The flightsim.to engine (ASO)

flightsim.to ranking inputs, in weight order: download velocity, rating count +
stars, title + thumbnail, recency.

### 7.1 Listing rebuild (this week)

- **Thumbnail:** the in-sim tablet/EFB with OPS ROOM loaded, cockpit visible. Not a
  logo — a logo is invisible in a feed of cockpit screenshots. 🔴
- **Title:** category + differentiator first. e.g. *"OPS ROOM — All-in-one Cockpit
  Ops Suite (Dispatch, Flight Watch, Black Box, RAAS) — Free"*.
- **Description:** hook → top-5 features → "replaces SimBrief + Volanta + Sky
  Dolly" → "free during public beta" → Discord CTA.
- **Cadence:** post a news update on flightsim.to every release, repurposing the
  release bot's changelog text.

### 7.2 The review engine (the growth hack)

Ratings are the marketplace's social proof and ranking input. 20+ reviews in week
one beats any feature. The loop:

- **In-app:** after the first successful flight (the aha moment), one ask —
  "Enjoying OPS ROOM? A flightsim.to review takes 30 seconds."
- **Discord:** release bot post ends with the review ask (one line).
- **Support:** every resolved bug gets "if this helped, a review would mean a lot."

Two touches max (aha moment + release post), then stop — nagging kills goodwill.

### 7.3 The "free" weapon

List as free, say **"free during public beta"** everywhere. Zero-price effect removes
the only download barrier; "during beta" is real scarcity, not fake urgency.

---

## 8. Content engine — searchable vs shareable

Every asset is either **searchable** (rank + convert) or **shareable** (reach +
links). Best assets are both.

### 8.1 Shareable (launch weeks 1–2)

| Asset | Hook | Distribution |
|---|---|---|
| 45s clip | Cockpit tablet tap → full app loads (first 3s) | Shorts/TikTok/Reels |
| 2–3 min walkthrough | "Your first flight with OPS ROOM" | YouTube |
| Black Box replay | Landing replayed in-sim with G/speed overlays | Shorts + Reddit |
| RAAS callout | "OPS ROOM just called my V-speeds" | Shorts |
| Screenshot set | Tablet + EFB + replay in cockpit context | flightsim.to + Reddit |

### 8.2 Searchable (compounds 6–12 months — build now, §12.6)

The search-demand map from research:

- "Volanta alternative free" — comparison page (marketing jiu-jitsu: rank on their brand)
- "SimToolkitPro alternative" — inherit the dormant product's demand
- "how to replay MSFS 2020 / 2024" — guide ending in OPS ROOM Black Box
- "best free MSFS flight tracker / logbook / black box" — roundup pages
- "MSFS 2024 EFB apps" — listicle that includes OPS ROOM (we're one of ~6)
- "you don't need Navigraph for MSFS 2024 + VATSIM" — the free-alternative angle
  (a Reddit thread with 90 answers proves demand 🟢)

Each page: keyword in H1, the honest comparison, a screenshot, a download CTA.

---

## 9. Community & Discord

The Discord is the retention and advocacy layer, and the bot already does most of
the hard work (welcome images, verify gate, self-assign roles, weather, VATSIM,
ATIS, logbook, releases). The gaps are attribution and advocacy — **§14** covers the
engineering.

- **#media / #cockpit-shots** channel for user screenshots; feature the best one
  monthly (role/credit). User cockpit screenshots are the highest-converting
  creative we can get for $0.
- **Support answered fast.** In a free product, support speed *is* the marketing;
  every solved problem is a future review.
- **Live leaderboard + FIDS in Discord** — the bot already ingests flight events;
  surface the leaderboard as a channel so the community is visibly alive.

---

## 10. Influencer & PR

- **Mid-size YouTubers (10k–100k subs):** "freeware roundup" and "MSFS essentials"
  channels. Lead with the in-sim tablet hook. Give early access + a ready-to-record
  setup + the three most clickable features. Use the existing `YOUTUBER_PITCH.md`.
- **FSElite:** pitch a news piece — "OPS ROOM ships a free in-sim tablet and native
  2024 EFB for the whole ops workflow." Devlog news is their bread and butter.
- **The EFB listicle angle:** "OPS ROOM joins the MSFS 2024 EFB, free, next to
  SimBrief and Navigraph" is a listicle writer's dream and ours to pitch.

---

## 11. Referral & advocacy loops

The trigger is the aha moment (first recorded flight), the action is "post your
cockpit screenshot," the reward is recognition (status), not cash — correct for a
free enthusiast product. 🔴

- **Trigger:** "Your first flight is in the logbook — share it."
- **Action:** one-click screenshot + pre-written caption with the flightsim.to link.
- **Reward:** Discord role ("OPS ROOM Pilot"), leaderboard placement, #media feature.
- **Referral:** Discord invite tracking (native) + a "Contributor" role for inviting
  N members. No code needed to start.

---

# PART C — OWNED-PROPERTY OPTIMIZATION (the repo work)

This is the section the earlier doc didn't have. Concrete changes to the app, bot
and website, with files named.

## 12. Website & SEO — the technical audit and fix list

### 12.1 What the site is today

- Vite + React 19 **SPA, client-side rendered.** Page content (changelog, features,
  leaderboard) is fetched via JS, so crawlers see near-empty HTML. 🟢 (verified in
  `src/`, `index.html`)
- `public/robots.txt` references `https://opsroom.live/sitemap.xml` but **no
  sitemap.xml exists** in `public/`. Broken reference. 🔴
- `index.html` has title/description/keywords/og/twitter but **no JSON-LD**
  structured data. No `og:image` (removed earlier), and `src/config/seo.js`
  `SITE.image` points at the logo mark PNG.
- Titles in `src/config/seo.js` are generic ("Modules: OPS ROOM",
  "Download: OPS ROOM") — not keyword-optimized.
- nginx is solid: HTTPS redirects, gzip, 6-month immutable asset cache, security
  headers. 🟢 (verified `nginx.conf`)
- Umami analytics is wired (`/api/analytics/record`, download-click tracking). 🟢
- flightsim.to social-proof badge is wired (`FlightsimBadge.jsx` +
  `admin-api/flightsim.py`). 🟢
- Live unique data on the site: community map, VATSIM FIDS, leaderboard — genuine
  SEO assets *if* rendered for crawlers.

### 12.2 The five fixes that move the needle (priority order)

**Fix 1 — prerender / SSR the marketing pages (highest impact).**
The site is fully client-rendered; Google can crawl it but slowly and unreliably,
and other crawlers (Bing, social scrapers, Discord) see nothing. Options in order
of effort:

- 🔴 **Recommended:** `vite-plugin-prerender` (or `prerender-spa-plugin`) to emit
  static HTML for the 5–6 pages that matter: `/`, `/features`, `/download`,
  `/faq`, `/changelog`, and the comparison/guide pages from §12.6. The marketing
  copy is static; only the live widgets (leaderboard/FIDS) need JS.
- For the live widgets, put a static fallback sentence in the prerendered HTML
  ("Live community leaderboard updates when you open the page") so crawlers still
  get meaningful text.

**Fix 2 — sitemap + robots.**
Generate `public/sitemap.xml` (list all routes; the build can emit it or it can be
a checked-in static file). Keep `robots.txt` as-is once the sitemap actually
exists. Submit it to Google Search Console and Bing Webmaster Tools.

**Fix 3 — JSON-LD structured data.**
Add to `index.html` (or the SEO component): `SoftwareApplication` schema with
`offers.price: 0`, `operatingSystem: Windows`, `applicationCategory:
GameApplication`, and `aggregateRating` fed from the flightsim.to badge. Add
`Organization` schema and `FAQPage` schema on `/faq` (this earns FAQ rich results
in Google).

**Fix 4 — keyword-optimized titles/meta.**
Replace the generic titles:

| Page | Current | Proposed |
|---|---|---|
| Home | "OPS ROOM: Professional Operations for Flight Simulation" | "OPS ROOM — Free MSFS Cockpit Ops Suite: Dispatch, Flight Watch, Black Box, EFB" |
| Features | "Modules: OPS ROOM" | "OPS ROOM Modules — Free Flight Recorder, Dispatch, RAAS for MSFS 2020 & 2024" |
| Download | "Download: OPS ROOM" | "Download OPS ROOM — Free MSFS Ops Suite (Windows)" |
| FAQ | "FAQ: OPS ROOM" | "OPS ROOM FAQ — Free MSFS EFB, Flight Recorder & Dispatch" |
| Changelog | "Changelog: OPS ROOM" | "OPS ROOM Changelog — v0.25.0" (dynamic per release) |

**Fix 5 — og:image.**
Use a real screenshot (the in-sim tablet in the cockpit, 1200×630), not the logo
mark. This fixes Discord/WhatsApp/Twitter link previews — a growth channel in
itself, since every shared opsroom.live link becomes a billboard.

### 12.3 Indexability checklist

- [ ] sitemap.xml exists and is submitted to GSC + Bing
- [ ] robots.txt points at a live sitemap
- [ ] canonical tags per page (SEO.jsx already emits them — keep)
- [ ] JSON-LD SoftwareApplication + FAQPage
- [ ] prerendered HTML for key routes
- [ ] og:image is a screenshot, not the logo
- [ ] `www` → apex 301 (nginx already redirects both names — confirm canonical)

### 12.4 Off-page SEO & backlinks

The niche is link-poor, so a handful of quality links moves rankings:

- flightsim.to listing → link to opsroom.live (do-follow? at minimum a cited source).
- FSElite news piece → backlink.
- YouTube video descriptions → links (Google counts these).
- Reddit threads → referral traffic + brand queries (Google weighs brand search).
- The comparison pages are built to *earn* links: "best free MSFS tools" roundups
  link to tools, not to ads.

### 12.5 Measurement

- Google Search Console: submit sitemap, watch impressions for "MSFS", "EFB",
  "flight recorder", "Volanta alternative".
- Umami: pageviews, download clicks (already), add installer-vs-portable click
  events (§13).
- Track: organic sessions, brand vs non-brand queries, ranking for the §12.6
  keywords.

### 12.6 The content/SEO page map (build in this order)

| Page | Target query | Type |
|---|---|---|
| `/compare/volanta` | Volanta alternative free | Comparison |
| `/guides/msfs-replay` | how to replay MSFS 2020/2024 | Guide |
| `/compare/simtoolkitpro` | SimToolkitPro alternative | Comparison |
| `/guides/msfs-efb-apps` | MSFS 2024 EFB apps | Listicle |
| `/compare/navigraph` | free Navigraph alternative / don't need Navigraph VATSIM | Comparison |
| `/best-free-msfs-tools` | best free MSFS tools | Roundup |
| `/guides/vatsim-dispatch` | VATSIM dispatch / FIDS | Guide |
| `/blog/*` | release notes repurposed as changelog posts | News |

Every page: keyword in H1, honest comparison (not a hit piece), a screenshot, a
download CTA, internal links to `/download` and `/features`. These are 10x-value
content — they rank for months and convert, unlike a tweet that dies in a day.

---

## 13. Website conversion optimization (CRO)

### 13.1 The current funnel

Home → Download → (installer or portable) → Getting Started guide. Umami records
the download click. Good baseline; these are the gaps.

### 13.2 Fixes

1. **Hero = the product, not the logo.** Replace the logo-led hero with the in-sim
   tablet screenshot, the one-line pitch, and two CTAs: "Download free (Windows)"
   + "See it in the cockpit."
2. **Social proof above the fold.** flightsim.to rating badge (wired), "free during
   public beta", "used by VATSIM pilots", and one real testimonial.
3. **One primary CTA on /download.** Installer = primary, portable = secondary
   (already installer-first — keep). Add "Free. No account required." as the
   reassurance line under the button.
4. **What happens after download.** A 3-step strip: download → run installer →
   first flight (links to Getting Started). Kills the "what now?" hesitation.
5. **Trust block.** Changelog cadence, active Discord, SHA256 verification, privacy
   note (local-first).
6. **System requirements** on /download (Windows 10/11, MSFS 2020/2024).
7. **FAQ page** gets the FAQPage schema (§12.2 Fix 3) and answers the questions
   people actually search ("is it free", "how to replay MSFS", "does it work with
   MSFS 2024", "does it need Navigraph").
8. **Analytics events:** distinguish installer vs portable clicks, and add a scroll
   event at the CTA. This tells you which half of the page converts.

---

## 14. Discord bot & server growth engineering

The bot already has: welcome images, verify gate, self-assign roles, weather,
VATSIM, ATIS, logbook, releases, support tickets. The growth gaps are attribution,
advocacy and discovery.

### 14.1 Attribution (one question, everything downstream)

Add a "How did you find us?" select to the welcome/verify flow, writing to the
existing `guild_settings` or `users` table. Options: flightsim.to, YouTube,
Reddit, VATSIM, Discord list, friend, Google, other. This is the attribution
system the whole plan depends on (§17). `src/bot/cogs/welcome.py` +
`src/bot/cogs/verify.py` are the touch points.

### 14.2 Advocacy (review + invite)

- **Review ask:** append one line to the releases cog's announcement ("Enjoying it?
  A flightsim.to review helps more than anything") — `src/bot/cogs/releases.py`.
- **Welcome DM/CTA:** the arrivals-channel welcome (`welcome.py`) should include the
  download link and the flightsim.to link, not just the verify prompt.
- **Invite reward:** Discord tracks invite uses natively. Add a "Contributor" role
  for members who bring N joins (a `guild_settings` counter + a monthly check).
- **#media channel:** the bot can post a weekly "share your cockpit screenshot"
  prompt and pin the best one.

### 14.3 Discovery (get the server listed)

- **Discord Server Discovery** (if requirements are met — this gives organic
  in-app discovery).
- **Server list sites:** Disboard, Discadia, top.gg, Discord.me — free listings,
  steady low-grade traffic.
- **Cross-promotion:** the bot's VATSIM/weather/ATIS commands are genuinely useful
  to non-members; make the `/invite` + server link prominent in every command
  footer and the bot's "about me."

### 14.4 The bot as a product, not just support

The bot already posts releases and ingests flight events. Two additions:

- **Leaderboard channel:** a channel that the bot updates with the live top-10
  (it has the data) so the community looks alive to new joiners.
- **"What's flying now" live feed:** the flight events already flow through
  `admin-api/community.py`; mirror the live feed into a Discord channel. A busy
  feed is social proof.

---

## 15. Product growth surfaces (desktop app)

The app is the distribution machine. Concrete additions:

1. **Review ask after the aha moment.** After the first logged flight (logbook
   write), surface a one-time, dismissible prompt: "Enjoying OPS ROOM? A
   flightsim.to review takes 30 seconds." Not at install, not nagging — once, at
   the moment of value. (`app/logbook.py` finalize + the UI layer.)
2. **Share-this-flight.** A button that captures a cockpit screenshot + a
   pre-written caption + the flightsim.to link, and drops it on the clipboard.
   IKEA effect: people share what they made. (`app/static/opsroom.js` + a new
   endpoint if needed.)
3. **Discord Rich Presence copy.** It already sets activity; make it read
   "OPS ROOM — flying {callsign} {dep}→{arr}" so every Discord friend sees the
   product in action. (`app/community.py`.)
4. **Onboarding attribution.** Add a "how did you hear about us" select to the
   onboarding wizard (`/api/onboarding/status` in `app/main.py`), written to
   `settings_store`. Ties install-time source to everything downstream.
5. **In-app changelog.** Show release notes in-app (already exists per the release
   flow) with the "free during public beta" line — drives re-engagement and the
   sense of an actively-developed product.
6. **In-sim watermark/share button.** The tablet/EFB UI gets a subtle
   "OPS ROOM" corner mark and a share button so cockpit screenshots carry the brand.

---

# PART D — EXECUTION

## 16. Psychology & conversion — the levers applied

| Principle | Where | The move |
|---|---|---|
| Zero-price effect | Every listing/CTA | "Free during public beta" as the headline |
| Social proof | flightsim.to + Discord + site | Drive review count; show "191k VATSIM pilots" |
| Scarcity (real) | Homepage + CTA | "Free during public beta" — honest, time-bounded |
| Reciprocity | Support + content | Give (free app, fast support, guides) before any ask |
| Contrast/anchoring | Comparison pages | "Replaces $X/mo of Volanta + Navigraph" makes free land |
| IKEA effect | First-flight moment | Ask users to share *their* flight, not to promote us |
| Loss aversion | Deferred to monetization | "What you'll miss when the beta ends" — later |

Warnings: fake urgency backfires (no countdown timers); repeated nagging kills
goodwill (two review asks max).

---

## 17. Measurement — the dashboard

Weekly, five rows + two SEO rows:

| Metric | Source | Week-1 target | 90-day target |
|---|---|---|---|
| flightsim.to downloads (7-day) | Creator dashboard | 500 | 5,000 |
| flightsim.to rating count | Listing | 20 | 100+ |
| Discord joins (7-day) | Discord | 50 | 500 |
| Website downloads (7-day) | Umami | 100 | 1,000 |
| Attribution split | Welcome/onboarding ask | live | 3 clear top sources |
| Organic impressions (MSFS queries) | Search Console | live | trending up |
| Brand vs non-brand search | Search Console | live | brand growing |

Channel rule (CMO skill): with a team of one, never run more than 3 active
channels. Anything outside the top three by week 6 gets paused.

---

## 18. The 90-day execution plan

### Weeks 1–2 — foundation + review wave

- Ship website SEO fixes: sitemap, JSON-LD, keyword titles, og:image, prerender.
- Rebuild flightsim.to listing (thumbnail, title, description, 0.25.0 news post).
- Ship the review ask: in-app (after first flight) + one line in the release bot.
- Add the "how did you find us" question (Discord welcome + app onboarding).
- Cut the 45s launch clip → Shorts/TikTok/Reels.

### Weeks 3–4 — borrowed reach + first content

- Send the YouTuber pitch to 20 mid-size channels.
- Pitch FSElite the "free in-sim tablet + native EFB" news piece.
- Publish the first two searchable pages: `/compare/volanta` and
  `/guides/msfs-replay`.
- Post the Reddit launch thread with the cockpit screenshot.
- Reach 3–5 virtual airlines with the adoption pitch.

### Weeks 5–8 — compound

- Publish the walkthrough video + 2–3 shorts.
- Publish `/compare/simtoolkitpro`, `/guides/msfs-efb-apps`, `/compare/navigraph`.
- Add the Discord leaderboard + "what's flying now" channels.
- Run the first monthly #media screenshot feature.
- Answer every flightsim.to comment within 24h.

### Weeks 9–12 — review and double down

- Pull attribution: which channel produced the top-3 sources?
- Kill/pause channels outside the top three.
- If reviews < target, run a one-week review-drive event in Discord.
- Decide the next "wow" product beat and its screenshot.

---

## 19. Risks & kill criteria

| Risk | Signal | Response |
|---|---|---|
| Weak flightsim.to listing | Low click-through vs downloads | Re-shoot thumbnail, A/B title in 2 weeks |
| Review engine not firing | <20 reviews by week 4 | Move the ask earlier (post-download, not post-flight) |
| SPA still not indexed | No impressions in GSC after 4 weeks | Prioritize prerender; verify with "site:" queries |
| Spread too thin | No channel >30% of signups | Cut to top 3 |
| YouTuber outreach silent | <2 replies in 3 weeks | Lead with the in-sim hook, shorter email |
| "Free" reads as "low quality" | Comments ask "what's the catch" | Add trust: changelog, active Discord, comparison pages |
| Monetization uncertainty | Users ask "will it stay free" | Be honest: free during beta, announce plans early |

**Kill criteria for the push:** if, after 30 days, flightsim.to downloads are <500
and review count <20, stop adding channels and fix the listing + review ask first.
That, not the features, is the product-market-fit test.

---

## Appendix A — repo inventory (what exists, what to change)

**Website (`opsroom-website`):**
- `index.html` — add JSON-LD, restore a good og:image, keyword title.
- `public/robots.txt` — keep, once sitemap exists.
- `public/sitemap.xml` — **create**.
- `src/config/seo.js` — keyword titles, screenshot og:image.
- `src/components/SEO.jsx` — add JSON-LD injection.
- `src/pages/*.jsx` — add comparison/guide pages; hero/CRO edits on Home/Download.
- `vite.config.js` — add prerender plugin.
- `admin-api/flightsim.py` — already serves the rating badge; feed it into JSON-LD.

**Bot (`ops-control-bot`):**
- `src/bot/cogs/welcome.py` — add download CTA + attribution ask.
- `src/bot/cogs/verify.py` — add attribution select to verify flow.
- `src/bot/cogs/releases.py` — add review CTA line to announcements.
- `src/bot/cogs/community.py` / `services/` — leaderboard + live-feed channels.

**App (`opsroom-app/source`):**
- `app/logbook.py` + UI — review ask after first flight.
- `app/static/opsroom.js` — share-this-flight button.
- `app/community.py` — Rich Presence copy ("flying {callsign}").
- `app/main.py` + `app/settings_store.py` — onboarding attribution question.
- Tablet/EFB package — brand corner mark + share button.

---

## Appendix B — sources

- SteamDB MSFS 2024: https://steamdb.info/app/2537590/charts/
- steamcharts MSFS 2024: https://steamcharts.com/app/2537590
- MSFS forums, Steam usage: https://forums.flightsimulator.com/t/flight-simulators-usage-data-on-steam-charts/717000
- VATSIM members (Wikipedia): https://en.wikipedia.org/wiki/Virtual_Air_Traffic_Simulation_Network
- flightsim.to / Sky Dolly listing: https://flightsim.to/addon/9067/sky-dolly
- "A Volanta Rival for FREE?" (YouTube) — free-vs-Volanta demand proof
- SimToolkitPro devlog (dormant): https://simtoolkitpro.co.uk/devlog/
- Navigraph MSFS 2024: https://navigraph.com/simulators/msfs2024
- MSFS forums "Third-Party EFB Apps" (short app list): https://forums.flightsimulator.com/t/third-party-efb-apps/739415
- "You don't need Navigraph for MSFS 2024 + VATSIM" (Reddit, 90 answers): https://www.reddit.com/r/MicrosoftFlightSim/comments/1pxt0rs/
- "10 MSFS Tools To Use Every Flight" (YouTube roundup format)

---

*Prepared with the launch-strategy, cmo-advisor, competitive-intel/teardown,
free-tool-strategy, app-store-optimization, content-strategy, referral-program,
seo-audit, marketing-ideas and marketing-psychology skill frameworks, plus live
research (Aug 2026) and a full read of the app, bot and website repos.*
