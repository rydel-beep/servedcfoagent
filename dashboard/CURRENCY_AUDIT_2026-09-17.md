# SYSTEM CURRENCY AUDIT — 2026-09-17

The month in one line: **the machine kept running; the humans went quiet.**
No dashboard login since **2026-08-13** (auth log); EDITH last spoken to
2026-08-10; the /ads board last rendered 2026-09-10. Every daemon thread
(sheet mirror 90s · GHL opp mirror 15min · snapshot 2h · sentinel hourly ·
attribution 6h) ran the whole month. The rot was in the jobs that only ran
on human action — and in the tracker's downstream columns.

## Per-source currency table

| Source / job | Stale since | Restored to | Lost / unrecoverable | Loudness verdict |
|---|---|---|---|---|
| Sheet mirror (7 tabs) | never — synced all month (last 32s before probe, 1518 rows) | current | none | ok (failures would have been silent `sync_state` rows — now a FAILING registry row → feed) |
| GHL opportunity mirror | never — synced all month (max created = today) | current | none | ok |
| **GHL contacts/notes mirror** | **2026-07-27** (7½ weeks) — the loop only synced opportunities; contacts refreshed ONLY on a manual "resync" chat command, and nobody logged in | **fixed**: kv-claimed DAILY contacts/notes pass added to the loop; full pass run post-deploy | contact/tag/note changes 27 Jul→17 Sep were invisible to the mirror until now (recovered — GHL retains them) | **SILENT → SEV1 class. Fixed structurally** (daily cadence + registry row) |
| **MRR snapshots** | 32 of 45 days missing — `take_snapshot` ran ONLY at boot; no deploys = no snapshots. Today's boot row was **null/0** (written before the roster built) | **fixed**: daily via the 2h refresh loop; null guard + self-heal overwrite; today's row healed with real data | **the missing 32 daily rows are UNRECOVERABLE** (per-day roster history was never captured) — NRR windows spanning Aug–Sep carry holes, stated wherever they render | **SILENT-ish**: the automations registry knew (30h cadence row) but only surfaced via greeting/whats-new — surfaces that need a login. **Fixed**: FAILING/STALE registry rows now publish to the action feed (`feed:extra:watchdog`) |
| Meta insights + daily-bucket archive | never — nightly `retention_archive_check` green all month | current | none (archive completeness watch found no missing recent days) | ok (misses would flag) |
| Stripe pull + canary | never — canary green on every 2h snapshot build + nightly | current | none | ok (LOUD twice over) |
| Xero (token refresh + P&L pulls) | never — pulls on every snapshot build | current | none | ok via `degraded[]` |
| Notion reads | on-request only (no job) | n/a | none | by design |
| ads_truth nightly sweep | never — stamped nightly incl. last night | current | none | ok — but see watchdog gap below |
| Sentinel L1/L2/L3 | never — L1 hourly all month, L2 nightly, L3 weekly (last 09-14) | current | none | ran fine — **but had NO watchdog: a dead loop would have been invisible forever. Fixed** (below) |
| Renewal sheet scan | nightly via L2 — current | current | none | ok |
| Review cycles (R-A2) | **ZERO review sessions since the 08-24 migration** — the 7–8-day human cadence never ran once | flagged (human cadence — can't be backfilled by the agent) | 3 review cycles' worth of pull/inject decisions never made | surfaced as the due-bulge in `review_flags` — on a board nobody opened. Now also in the drift register |
| Date-resolution / supersession | nightly — current (derived epoch fresh) | current | none | ok |
| Forecast accuracy log (`record_projection`) | **never ran — zero production callers since it shipped** (dead code) | flagged | no accuracy history exists | silent by omission — registered in the drift doc |

## The watchdog fixes (a dead nightly must alert)

1. **Mutual watchdog**: the 2h snapshot-refresh loop now calls
   `automations.publish_feed_state()` — any FAILING/STALE `cfo:*` registry
   row becomes a self-retiring ACTION-FEED item (`feed:extra:watchdog`),
   not just a salience whisper. In return, sentinel **L1 now watches** the
   snapshot's age (>5h → LOUD), the sweep stamp (>1d → LOUD — this also
   un-silences the L2 gate, which skips every nightly watch when the sweep
   hasn't stamped), and L2's own age (>36h → LOUD).
2. **Registry rows added**: `cfo:ad_sentinel_l1` (3h), `cfo:ad_sentinel_l2`
   (30h), `cfo:ads_truth_sweep` (30h) — the sentinel is now a SUBJECT of
   the health registry, not just its author.
3. **MRR daily cadence** in the refresh loop + null-row guard + self-heal.
4. **GHL contacts daily** in the mirror loop (kv-claimed, read-only GETs).
5. Residual risk, stated: if BOTH loops die at once, the last alert path is
   Railway's /health check — external uptime alerting is Rydel's call
   (flagged, not built).

## Why nothing screamed for a month

Every loudness lane that fired ended at a surface that requires a login
(greeting, what's-new, action feed, /ads board). The feed items were THERE
(sentinel escalations show closes-band signals through the month). The
structural fix above widens what reaches the feed; the organisational fix
(an outbound push when the feed goes red — e.g. the Lark brief on the
timeline service) is flagged for Rydel, out of this repo's scope.
