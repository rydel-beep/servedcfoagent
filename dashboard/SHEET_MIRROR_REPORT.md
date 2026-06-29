# POSTGRES SHEET-MIRROR — Phase 0 (inventory + schema + scope) — HARD STOP

**Date:** 2026-06-25 (Sydney) · **Scope:** served-cfo-agent only · **Status:** HARD STOP — confirm
scope (focused vs all) + approve the schema before building. Nothing built yet.

## Architecture
```
RAW SHEETS (source of truth)
  → SYNC JOB (the only thing hitting the slow Sheets API; by tab NAME)
    → POSTGRES MIRROR (faithful jsonb copy of sheet rows; ms reads, no rate limit)
      → EDITH reads the mirror for every answer
Freshness: (1) background sync ~90s · (2) voice/text "resync" = immediate pull · (3) transparency panel.
```
Honest model: there is always a sync step (Sheets can't stream to a DB). The win is making sync
fast + frequent + forceable so it *behaves* like a direct connection — ms-fresh on read,
seconds-fresh on data. Not literal direct-wiring.

## 1. Dependency map — every tab EDITH reads (by NAME, live row counts)

**Lead-to-Cash book** (`1BrL-xh…reDY`):

| Tab (by name) | Rows | Feeds | Churn |
|---|---|---|---|
| **Lead-to-Cash Tracker** | 1,200 | funnel (closes/leads/sets/shows), cash collected, closer comms, won deals, velocity, lead quality | **HIGH** (the closes problem) |
| **Team Scorecard** | 52 | computed funnel cells (closes=4), setter payout (scorecard $50/set) | HIGH |
| **SETTER PAYOUT LOG** | 1,607 | setter comm ($50/set + 5% cash) → loaded CAC; payout status | MED |
| **Setter Deep-Dive** | 22 | setter activity (dials, speed-to-lead) | LOW |

**Finance book** (`1n7OcGr…CTg`):

| Tab (by name) | Rows | Feeds | Churn |
|---|---|---|---|
| **Health** | 37 | active-client roster, current/next MRR, trend, churn risk | MED |
| **RECOGNIZED** | 52 | recognized revenue, forward-MRR (churn-adjusted) | LOW |
| **SALARY** | 19 | payroll baseline, team_model, true_team_cost, burn | LOW |

(Stripe/Xero are APIs, not sheets — out of scope for the sheet-mirror; they already read live.)
NB: today the code reads **Health by gid 1407663952** and the **payout log by gid 552970662 (→ 400)**
— the mirror will read everything **by name** (the proven-correct path).

## 2. Scope — RECOMMENDATION: focused-then-expand

Start with the four tabs that drive the closes/cash/clients/comms problem (and the "last 5 closes"
acceptance gate), prove the pattern, then add the low-churn three:

- **Phase-1 mirror (focused):** Lead-to-Cash Tracker · Team Scorecard · SETTER PAYOUT LOG · Health
- **Expand later:** Setter Deep-Dive · RECOGNIZED · SALARY

Rationale: the "recent closes invisible" pain is entirely in the Lead-to-Cash Tracker + Team
Scorecard; SALARY/RECOGNIZED barely change. Focused first = faster to the acceptance gate, lower
blast radius. (Alternative: mirror all 7 at once — same schema, just more sync work up front.)

## 3. Mirror schema (generic, faithful — no transform drift)

A single generic table stores each tab's rows as raw cells (jsonb array) — faithful copy, survives
column add/rename, downstream parses the same way it parses CSV today:
```sql
CREATE TABLE IF NOT EXISTS sheet_mirror (
  tab           text  NOT NULL,   -- canonical key, e.g. 'ltc_tracker'
  row_index     int   NOT NULL,   -- source row index (stable key)
  cells         jsonb NOT NULL,   -- raw row cells as a JSON array (NO transformation)
  row_hash      text  NOT NULL,   -- md5 of the row (skip-unchanged)
  synced_at     timestamptz NOT NULL,
  PRIMARY KEY (tab, row_index)
);
CREATE TABLE IF NOT EXISTS sheet_sync_state (
  tab            text PRIMARY KEY,
  book_id        text,  tab_name text,  feeds text,
  last_sync_at            timestamptz,  -- last CHECKED
  last_change_detected_at timestamptz,  -- last actually CHANGED
  last_sync_status text,                -- ok | failed
  row_count      int,
  content_hash   text,                  -- whole-tab hash (change detection)
  last_error     text
);
```
Migration is idempotent (`CREATE TABLE IF NOT EXISTS`), added to the existing `db.migrate()` chain.
Reuses the **existing Postgres** (memory instance; `DATABASE_URL`, `db.get_conn()`) — no second DB.

## 4. Change detection — full-pull-and-hash

Sheets' CSV export gives no reliable cheap revision signal, so each sync **pulls the tab by name and
hashes it**:
- compute `content_hash` over all rows; if **unchanged** vs `sheet_sync_state.content_hash` → update
  only `last_sync_at` (checked, not changed) and skip the upsert (cheap).
- if **changed** → upsert rows by `row_index` (insert new, update by `row_hash`), **delete mirror
  rows beyond the new row count** (propagate removals), set `last_change_detected_at = now`.
The pull is the only API cost; hashing is local. 7 small tabs every ~90s is light (and only the
sync touches the API — EDITH never does on the hot path).

## 5. Atomicity / resilience
- Each tab syncs in a transaction; a failed/partial sync **keeps the last-good mirror** and sets
  `last_sync_status=failed` + `last_error` (loud, never silent stale). One tab failing doesn't break
  others. Backoff on Sheets rate limits. Postgres-down → degrade loudly + fall back to a direct live
  read where feasible.

## 6. Postgres reachability
`DATABASE_URL` is set; `db.py` (get_conn/migrate/memory_online/schema_overview) is the live memory
instance — proven reachable from the **deployed app** (memory features run on it). Not reachable
from my local railway-run (Railway-internal hostname) — mirror ops will be verified via the deployed
app, as with Stripe/Meta.

## Implementation note (entanglement)
A parallel session is editing `snapshot.py`/`sales_analytics_pull` is clean. I'll add a new
`sheet_mirror.py` (tables + sync + mirror-backed `fetch_tab(tab)`), and re-source the pulls via a
small swap of their `_fetch_tab` to read the mirror — keeping `snapshot.py` edits minimal and
committing only my hunks (as every round).

## HARD STOP — Rydel confirms before building
1. **Scope:** focused-first (Lead-to-Cash Tracker · Team Scorecard · SETTER PAYOUT LOG · Health) then
   expand — or mirror all 7 now?
2. **Schema approved?** (generic jsonb `sheet_mirror` + `sheet_sync_state`, on the existing Postgres.)

---

## Phases 1–5 — built (focused 4 tabs; schema approved)

**`sheet_mirror.py` (new):** `sheet_mirror` (raw rows as jsonb) + `sheet_sync_state` on the existing
memory Postgres (idempotent migrate, run on boot). Mirrors the 4 tabs **by name** — except **Health
by gid 1407663952** (proven: the tab literally named "Health" is an MRR-projection view with 37 rows;
the real 38-active roster is the gid). `sync_tab` is atomic + faithful (raw rows, no transform):
unchanged content-hash → bump *last-checked* only; changed → replace rows in a transaction (handles
inserts/updates AND removals) + stamp *last-changed*; failure → keep last-good mirror + flag
`sync_state` loudly. `sync_all` is lock-guarded so the background loop and a manual resync never
collide.

**Reads (Phase 2):** `sales_analytics_pull._fetch_tab`, `finance_sheets_pull._fetch_tab_by_gid`, and
`loaded_cac` now read the **mirror first** (`read_by_name`/`read_by_gid`) and fall back to a live
Sheets read when a tab isn't mirrored / is stale (> `SHEET_MIRROR_MAX_STALE_SECONDS`, default 600) /
the DB is down. Same metric logic, just sourced from Postgres — no per-question Sheets pull on the
hot path.

**Freshness (Phase 3):** background loop every `SHEET_SYNC_INTERVAL_SECONDS` (default **90s**) —
only the sync hits the API and unchanged tabs are skipped, so it's cheap. **Voice/text "resync"**
("resync" / "sync now" / "pull the latest" / "refresh your data") → immediate `sync_all` **+ snapshot
rebuild** (so EDITH's answers reflect the fresh data, not the last persisted snapshot) → EDITH
confirms per-tab row counts + the **latest close**. Also `POST /dashboard/api/resync` (panel button +
Cmd-K). Concurrency guarded by a lock.

**Transparency (Phase 4):** `/dashboard/data-sources` panel + `GET /dashboard/api/data-sources` +
voice "what's plugged into your system / is your data current" → per-tab source, feeds, *last
checked* vs *last changed*, row count, OK/FAILED status + error. A failed sync shows loudly; EDITH
proactively flags it rather than serving stale rows silently.

**Degradation (Phase 5):** Postgres down or a tab stale → reads fall back to a **live Sheets read**
(never crash, never silent-nothing). A mid-sync sheet failure keeps the last-good mirror + flags
degraded. Read-only from Sheets throughout.

**Tests:** 246 pass (+8 sheet_mirror: fetch URL name-vs-gid, hashing, lookup maps, resync/sources
command detection, graceful no-DB). Live DB sync/read + the **"last 5 closes" acceptance gate**
(resync by voice → EDITH names the latest closes) verified on the deployed app (the Railway-internal
Postgres isn't reachable from local).

---

## Addendum — Leads visibility (2026-06-29)

**The gap:** a live test showed EDITH could name recent CLOSES (Lovefish, The Cally Hotel) but not
the latest LEAD entered — she said she "only sees aggregated snapshot data."

**Phase 0 (verified, not assumed):** gid `1923956551` Rydel pointed at = **the same Lead-to-Cash
Tracker already mirrored** (53 cols; header "1 · LEAD INTAKE": Lead ID, Input Date, Input Time, Lead
Name, Email, Phone, Lead Source, Business Name → through the close columns). The 1-row diff is the
banner row. So the **mirror already holds every lead** — leads and closes are the same rows (a LEAD =
a row with Input Date + Lead Name; a CLOSE = Call Outcome == "won"). The gap was purely **surfacing**:
the snapshot exposed closes, never "latest lead." Mirror reads by NAME ("Lead-to-Cash Tracker") as
required.

**Fix (`leads_view.py`):** reads the mirrored tracker, returns the most-recently-entered leads sorted
by Input Date + Time (newest first). Surfaced via:
- voice/text: "who's the latest lead?" → names it; "recent leads" → a short list;
- the **resync confirmation** now names the latest LEAD alongside the latest CLOSE;
- `GET /dashboard/api/leads?limit=N`.
PII-safe: Email/Phone columns exist but are **never returned or logged** — only Lead Name, Business,
Source, intake time (auth-locked surface).

**Acceptance (this addendum's headline):** "who's the latest lead?" → EDITH names the newest tracker
lead (e.g. The Takeout Co., 2026-06-29); "last few closes" still correct; enter a lead → "resync" →
EDITH knows it immediately. 269 tests pass (+4).
