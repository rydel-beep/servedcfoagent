# EDITH — Chat 404 + Google Sheets Freshness Diagnosis

_Generated 2026-06-16 (Sydney). Scope: chat model config + Sheets read/freshness path only.
HUD, voice pipeline, and engine math untouched._

---

## ISSUE A — Chat API 404 (BLOCKING) — ROOT CAUSE FOUND & FIXED IN CODE

### Symptom
```
Chat API error: Error code: 404 - {'type':'error','error':{'type':'not_found_error',
 'message':'model: claude-sonnet-4-20250514'}}
```

### Root cause
A **retired model identifier, hardcoded** in the chat handler.

- The only Anthropic call site in the entire codebase is `dashboard/chat.py`
  (`client.messages.create`). The greeting / brief / voice paths are template-driven
  and never call a model, so chat was the *only* — and a totally — broken LLM surface.
- The model was a **hardcoded string literal** at `dashboard/chat.py:348`
  (`model="claude-sonnet-4-20250514"`). There was **no** `CHAT_MODEL` / `ANTHROPIC_MODEL`
  env var and **no** entry in `config.py`, so the string could only be changed by editing
  code — that is the drift that allowed this to rot.
- `claude-sonnet-4-20250514` is the **dated full ID for the original Claude Sonnet 4**,
  whose **retirement date is 2026-06-15**. As of **2026-06-16** the Anthropic API returns
  `404 not_found_error` for it. Not a key problem, not a Sheets problem — the model string
  simply no longer resolves.

### The fix
- **New single source of truth** in `config.py`: `CHAT_MODEL = os.getenv("CHAT_MODEL", "claude-sonnet-4-6")`.
  Every Claude-calling endpoint (currently just chat) reads this, so the string can never
  drift across endpoints again.
- **`dashboard/chat.py`** now does `from config import CHAT_MODEL` and passes `model=CHAT_MODEL`.
- **Default model: `claude-sonnet-4-6`** (Claude Sonnet 4.6) — the documented drop-in
  replacement for retired Sonnet 4. Same Sonnet tier, 1M context. `temperature=0.5` at the
  call site remains valid on Sonnet 4.6 (sampling params are only removed on the Opus 4.7/4.8
  and Fable tiers), so no other change was needed.
- Because the **in-code default is already a valid model**, the 404 is fixed on the next
  deploy *regardless of whether the Railway env var is set*. The `CHAT_MODEL` env var is the
  future-proof override (e.g. to bump to `claude-opus-4-8` later) — not a requirement.

### Verification
- `claude-sonnet-4-20250514` removed from all executable code (one reference remains, in a
  config.py comment, as deliberate history).
- `config.py` + `dashboard/chat.py` parse clean; `from dashboard import chat` imports OK and
  resolves `CHAT_MODEL = claude-sonnet-4-6`; env override confirmed working.
- `tests/test_voice.py` + `tests/test_dashboard.py`: **32 passed**, no regression.
- **LIVE ping: PASSED (2026-06-16).** Pushed to `origin/main` (commit a5bb464) → Railway
  (project `athletic-gratitude` / service `CFOagent` / production) built. Pinged
  `claude-sonnet-4-6` against the **production Anthropic key** via `railway run` (key never
  exposed) → **200 OK**, API-resolved model `claude-sonnet-4-6`, reply `"Pong!"`. No 404.
- **Railway env var set:** `CHAT_MODEL=claude-sonnet-4-6` on CFOagent/production (explicit
  override; in-code default matches).

### Model string now in use
`claude-sonnet-4-6` (via `config.CHAT_MODEL`; Railway env var `CHAT_MODEL` set to the same).

---

## ISSUE B — Google Sheets freshness audit (Phase 1 — DIAGNOSIS ONLY)

> Hard stop: **no fetch logic changed.** This is the map + verdict for Rydel to approve Phase 2.

### B.1 — Full data map (every Sheets read)

Two books. **LTC** = Lead-to-Cash `1BrL-xhKSm1rW9RwwkWneqcrvGKQp5D-AfAkKeRUreDY`.
**FIN** = Finance `1n7OcGrOsdWb6OgFqZHzOYCcgUG8U4P3qWwy89w00CTg`.

| Module / fn | Book | Tab selector | Endpoint | Range | Feeds | Live status |
|---|---|---|---|---|---|---|
| `sheets_pull.pull_sheets` | LTC | `sheet="Lead-to-Cash Tracker"` (by NAME) | gviz | whole tab (1173 rows) | won-deal cash, contract value, net cash, closer/setter commission, offer mix | ✅ 200 |
| `sales_analytics._fetch_tab("Team Scorecard")` | LTC | by NAME | gviz | whole tab | funnel cross-check | ✅ 200 (name path works) |
| `sales_analytics._fetch_tab("Setter Deep-Dive")` | LTC | by NAME | gviz | whole tab | per-setter throughput | ✅ 200 (name path) |
| `sales_analytics._fetch_tab(SHEET_CONFIG.tab_name)` | LTC | "Lead-to-Cash Tracker" by NAME | gviz | whole tab | velocity / multi-window | ✅ 200 |
| `sales_analytics._pull_payout_log_footer` + `_pull_commission_detail` | LTC | gid `552970662` (was `1862317163`) | `/export?gid=` | whole tab (143 rows) | setter payout detail | ✅ **FIXED 2026-06-16** |
| `finance_sheets.pull_salary_baseline` | FIN | `sheet="SALARY"` (by NAME) | gviz | whole tab | payroll baseline (`true_team_cost`) | ✅ 200 |
| `finance_sheets.pull_recognized_revenue` | FIN | `sheet="RECOGNIZED"` (by NAME) | gviz | current-month col | recognized (accrual) revenue | ✅ 200 |
| `finance_sheets.pull_client_health` | FIN | **gid `1407663952`** (`_HEALTH_TAB_GID`) | `/export?gid=` | whole tab | active clients, MRR, trend, projections | ✅ 200 |
| `forward_mrr._fetch_recognized_tab` | FIN | **gid `1407663952`** (calls it "RECOGNIZED") | `/export?gid=` | month cols | forward-MRR projection | ⚠️ **200 but WRONG TAB** |

### B.2 — Defects found

1. **Payout-log read was hard-broken — STALE GID. ✅ FIXED 2026-06-16.** `_PAYOUT_LOG_GID = 1862317163`
   pointed at a **since-deleted/rebuilt tab**, so `/export?gid=1862317163` returned HTTP 400 (Google
   served an HTML error page, not CSV) and setter payout detail silently came back `[]`. Rydel supplied
   the live gids: **Setter Payout Log = `552970662`**, Closer Payout & KPI = `115293898`. Both
   functions (`_pull_payout_log_footer`, `_pull_commission_detail`) read the **Setter** log, so
   `_PAYOUT_LOG_GID` was repointed to **`552970662`**. Verified live: **143 rows fetched**; footer
   totals reconcile — **owed $6,201.95 = paid $3,404.31 + pending $2,797.63**. (Closer Payout & KPI tab
   `115293898` is *not* read by any engine — closer commission is derived from the main LTC Tracker +
   `CLOSER_COMMISSION_BY_OFFER` per source-of-truth precedence. Sourcing closer KPI from that tab would
   be a new feature, not a bug fix — flagged for Rydel.)

   _Correction to an earlier interim finding:_ the 400 was **not** because the LTC book blocks
   `/export` — with a **valid** gid, `/export?gid=` returns 200 for the LTC book (e.g. 552970662,
   115293898). The earlier "`/export` 400s book-wide / gviz ignores gid" reading was an artifact of
   probing **invalid (deleted) gids** — gviz falls back to the default tab for an unknown gid (hence the
   identical 27-row guardrail tab), but **honors valid gids**. Lesson logged: the gate against silently
   repointing caught this before any wrong change shipped.

2. **`forward_mrr` reads the wrong tab — STILL OPEN (needs Rydel).** gid `1407663952` is confirmed by
   live probe to be the **Health tab** (header: `Client Name, Status, Package Type, … Monthly Recognized
   Revenue, …, January 2026 …`). `finance_sheets.pull_client_health` uses it correctly *as* Health. But
   `forward_mrr._fetch_recognized_tab` fetches the **same gid** while its docstring/var call it "the
   RECOGNIZED tab" — so forward-MRR projections are built off the **Health** matrix, not RECOGNIZED. A
   gid is exactly one tab, so this is a genuine source mismatch (or at best a misleading label).
   **Not changed — confirm intent before repointing** (per CLAUDE.md "do not silently repoint").

### B.3 — What `gid=239343371` is (the tab Rydel was checking)

- It is a tab **in the LTC book**. **No engine reads it** — zero references to `239343371` anywhere in
  the codebase (confirmed by grep).
- Its content could not be read directly (`/export?gid=` 400s; gviz ignores the gid), but it is **not**
  the main "Lead-to-Cash Tracker" tab EDITH actually reads (that tab is 1173 rows, fetched by name).
- **RESOLVED 2026-06-16 (Rydel):** `gid=239343371` is a **manual scratch/summary tab** — **do NOT
  wire it.** EDITH never sources from it by design. This **explains the "not up to date" perception**:
  Rydel was eyeballing a scratch tab and comparing it to EDITH, which reads the main tracker tab (by
  name) + the FIN Health/RECOGNIZED tabs. The mismatch was a source-comparison artifact, not staleness.

### B.4 — Freshness mechanism (how/when data refreshes)

- **No per-read cache / TTL.** Every pull does a live `requests.get`. The de-facto cache is the
  persisted snapshot file.
- **Refresh triggers (3):** (a) **startup auto-refresh** — on boot, rebuilds if the snapshot is
  missing/incomplete or **>4h old** (`_STALE_THRESHOLD`); (b) **scheduled daemon thread** — rebuilds
  every **`REFRESH_INTERVAL_HOURS` (default 6h)** if >4h stale; (c) **manual** — `POST /cfo/refresh`
  (X-CFO-KEY) and dashboard `/api/refresh`. So in steady state EDITH's data is **≤ ~4–6h old**, not
  arbitrarily stale. (The 6h thread was added specifically because it "went 4 days stale" before.)
- **Persistence is EPHEMERAL.** `SNAPSHOT_FILE` defaults to `snapshot_state.json` in the app dir;
  **gitignored** and **not** redirected to a `/data` volume on Railway (verified `SNAPSHOT_FILE` unset).
  So every deploy/restart **loses** the file — but startup auto-refresh rebuilds it on boot, so prod is
  not left empty. (This very deploy of the chat fix restarted the container and will have triggered a
  rebuild.)
- **Two gunicorn workers**, each with its own in-memory `_current_snapshot` and its own refresh thread,
  all writing the one shared `snapshot_state.json`. Chat reads `load_persisted()` (the file) every
  request, so chat sees the shared file — consistent. App.py JSON endpoints read per-worker memory, so
  a manual refresh on one worker isn't reflected by the other until its own next refresh — a minor
  cross-worker inconsistency window, not a staleness root cause.
- **Auth: Sheets need NO credentials** — all reads are public gviz/`/export` CSV. So "auth expired" is
  **not** a Sheets failure mode. (Xero/GHL *are* unconfigured — see degraded list — but those are out
  of this scope.)

### B.5 — Last snapshot health (local file, 2026-06-12 14:35, `ok:false`, 10 degraded)

Sheets-related degradations: 1 blank closer-commission, 8 blank setter-commission (data-entry, not
staleness), funnel mismatch (computed vs Team Scorecard). Out-of-scope but notable: Xero not configured,
GHL not configured, Stripe MCP miscounting subscriptions, cash override 8 days stale.

### B.6 — FRESHNESS VERDICT

**EDITH is mostly reading current data** (≤4–6h via the scheduled refresh), **but three things make it
look stale/wrong**, in priority order:

1. **Source mismatch on the human side** — Rydel checks `gid=239343371`, which **no engine reads**.
   EDITH reads a different tab. Resolve by confirming which tab is authoritative. **STILL OPEN.**
2. ~~Payout-log tab silently empty~~ **✅ FIXED** — stale gid `1862317163` → `552970662`; 143 rows,
   totals reconcile.
3. **forward-MRR is reading the Health tab, not RECOGNIZED** (gid 1407663952 mislabel) — projection
   source is wrong/misleading; confirm intent before repointing. **STILL OPEN.**

### B.7 — Phase 2 status

- ✅ **Payout-log fixed** (`_PAYOUT_LOG_GID` → 552970662, verified live). Shipped (commit d1d6c2b).
- ✅ **`forward_mrr` repointed** to read **RECOGNIZED by name** (commit fa81087). Before/after numbers
  identical today — source-correctness fix, no number shift.
- ✅ **`gid=239343371`** resolved — manual scratch tab, intentionally not wired (Rydel).
- ✅ **Freshness UX shipped:** header pill now reflects **data health** (red dot + issue count when
  `ok:false`/degraded, not just age), with an explicit **"Data as of &lt;Sydney time&gt;"** tooltip;
  the Data Quality panel shows the formatted "Data as of" time; the **manual refresh** button now
  surfaces success/failure loudly instead of failing silently.
- ⏳ **Closer Payout & KPI tab (115293898)** — not read; surfacing it is a new feature. Awaiting Rydel.
- ⏳ **Per-source last-fetch time & row count** — deeper readout; needs the snapshot to record per-source
  fetch metadata. Not built (avoids scope creep); degraded[] already names failing sources. Available
  on request.
- ⏳ Optionally persist the snapshot to a `/data` volume so it survives deploys (set `SNAPSHOT_FILE`).
  Currently mitigated by startup auto-refresh on boot.
