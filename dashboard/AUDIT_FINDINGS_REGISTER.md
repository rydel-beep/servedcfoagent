# ADS EXTREME AUDIT — FINDINGS REGISTER

Status: **GATE CLOSED — FIX WAVE SHIPPED (2026-08-09).** Discovery artifacts in
`dashboard/audit_artifacts/` (00–05 + drills_phase_b.py); gate-close artifacts
06+ (fix-wave suite run, scorecard v1, live migration logs). Rulings R1
encoded (DECISIONS #132). Order ran as ruled: F5 promoted FIRST (silent-lie
class on the money columns), then F6 · F2 · F1 (isolated) · F8 · hardening ·
polish · Phase H sentinel · scorecard v1.

Every CLEARED entry names its root cause, regression test, and fresh artifact.
A finding without a fresh re-run artifact is NOT cleared — no audit theater.

## SEV1

**F4 · Anonymous financial-data exposure + credential burner — CLEARED
(hotfix `45670b7`, 2026-08-08).** /debug/* X-CFO-KEY-gated, live-verified 401.
Test: `tests/test_debug_route_auth.py` (any ungated /debug route fails the
suite). Fresh artifact: the L3 sentinel security replay re-probes the gate
weekly (`ad_sentinel.security_replay`, proof `tests/test_sentinel.py::
test_l3_weekly_all_legs` — 401/401, artifact 06).

## SEV2 — the correctness wave

**F1 · Cold roster/drill 5.7–15.8s vs 500ms budget — CLEARED.**
Root cause: the roster path REQUIRED a live engine result; the cache is 30-min
TTL, per-worker (×2), per-key — the common case was a full engine build.
Fix: the board layer persists an ENGINE SLICE (creatives WITH I17 member lists
+ trimmed view rows) beside every rollup (`dashboard/ads._engine_slice`);
`roster_engine.load_result` serves rosters AND both dossier legs from it when
the engine is cold — stale-LABELLED like the grid, background warm kicked.
Measured (sandbox, engine build mocked at 6s so it would blow the timer if on
the path): cold roster via rollup **median 0.0ms · max 0.3ms** (n=20); live
projection = kv read (~33ms) + enrichment (~0.2s warm-measured at audit) ≈
0.25s < 500ms. Warm path unchanged (0.2s). Tests: `tests/test_rollup_rosters.py`
(5 tests incl. budget timer + rollup-path I17). ISOLATION HELD: grid consumers
re-run green (test_ads_dashboard / test_ads_ux, artifact 06); I17 re-swept in
FULL post-change — sandbox full sweep `test_i17_full_sweep_on_rollup_path`
zero drift + live full sweep via `ad_sentinel.full_i17_sweep()` (artifact 07).
Also fixed inside the same finding: the serve path's warm check probed
`AE._cache` with a stale hand-built 3-tuple and NEVER hit (dead warm path) —
consumers now use `AE.cache_fresh()`.

**F5 · degraded[] invisible on /ads ($0-spend illusion) — CLEARED (ran FIRST
by ruling).** Root cause: degradation signals produced at source were carried
in payloads but dropped before the UI — adsapp.js had zero `degraded` reads;
`money(0)` rendered a dead Meta token as a REAL $0 spend / $0 CPL (an
actionable lie on the allocation surface). Fix: degraded[] + ok now ride the
board/roster/dossier payloads; every spend-derived cell (spend, CPL, C/Qual,
C/Set, C/Close, loaded, LTGP:CAC) renders a **DEGRADED chip** (source +
reason, never $0, never a real-looking '—') on the grid, headline tile,
dossier econ legs; a LOUD banner strip lists degraded sources; the hygiene
block states unavailability instead of vanishing. FAMILY SWEEP (the class,
not the instance): entity-map degradation was carried in its store but
dropped by compute — now folded (deduped) into result.degraded; the sales-
summary text export built from a degraded snapshot now states it; every other
JS surface audited (dashboard.js already renders; chat/edith/memory/export
payload map checked — export was the one gap, fixed). Tests:
`tests/test_ads_degradation.py` (8 — dead Meta + dead entity map + empty
contacts each land in degraded[], payload carriage on all three routes, JS/CSS
render contract, export statement). Artifact 06.

**F6 · Derivation writes leave stale-labelled-fresh caches — CLEARED.**
Root cause: no derivation write touched the engine cache or rollups; applied
cards showed OLD values labelled fresh ≤30min. Fix: kv `derived:epoch` —
bumped by EVERY derivation-class write (record/supersede/show-verification/
spine/reached — F6 call sites in resolution.py + ads_truth.py), folded into
the engine cache key (`cache_key`/`cache_fresh`), stamped on every rollup;
an epoch-mismatched rollup serves stale-LABELLED with the reason
("superseded by a derivation write — refreshing") + auto-refresh; old-epoch
cache entries pruned on write. Global invalidation by design — correctness
first; per-key narrowing is a later optimization. Tests:
`tests/test_cache_invalidation.py` (4). Artifact 06.

**F2 · Trust-journal evidence horizon ~2 days — CLEARED.**
Root cause: one 200-cap rolling log for BOTH sweep noise and evidence; the
#131 charge-id evidence was aging out ~2 days after conversion. Fix: the
journal is PARTITIONED — evidence-class rules (derivations, supersessions,
ruling conversions, verifications, F8 re-derivations, sentinel heals) also
land in durable `resolution:journal` (cap 1000 ≫ the derivation population,
which is bounded by the lead universe); sweep noise stays in the 200-cap
rolling view. Tests: `tests/test_evidence_horizon.py` (5 — incl. the drill
re-run: a >2-day-old charge-id entry survives a 500-entry sweep flood).
Artifact 06.

## SEV3 — hardening

**F3 · Stale invariant alerts never retire — CLEARED.** The nightly sweep now
collects the union of LIVE violation ids across both clocks × 3 windows and
retires (journaled) every invariant-class pending whose condition cleared —
the A5 self-retiring doctrine applied to this class; live conditions survive
(condition-driven, not a wipe). Test: `tests/test_hardening_wave.py::
test_stale_invariant_pendings_retire_when_clear`.

**F8 · Derived dates used the UTC day — CLEARED (doctrine violation fixed at
the source helper).** `helpers.sydney_day()` is THE derivation-boundary
conversion (ISO/datetime/date, DST-correct); routed through it: ads_truth
`_date_of` + call dates, resolution's GHL-won and contact-created rungs, the
engine's IG-inquiry windowing. Journaled re-derivation
`resolution.rederive_ghl_dates_sydney()` re-reads every ghl-appt / contact-
created derivation from its evidence (old→new + evidence id + reason
"F8-sydney-day", idempotent, dry-run mode, window-boundary crossings called
out, one epoch bump) — LIVE RUN post-deploy (artifact 08); reconciliation
re-checked green after. DST pinned: Oct 2026 transition cases in
`tests/test_sydney_day.py` (9 tests incl. drill B9's exact timestamp).

**F9 · Stripe pagination partial-failure absorbed silently — CLEARED (drill
B13 re-run).** A page error after partial data now STOPS the pull and marks
kv `stripe:partial_pull` (cleared on the next clean pull; pagination-cap
truncation also marks); the cash view carries a core degraded entry; the #131
ruling pass SKIPS the run loudly; the P1 card builder keeps existing cards
instead of rebuilding from a fragment. Tests: `tests/test_hardening_wave.py`
(5 F9 tests).

**F16 · Nightly double-run race — CLEARED.** The day is claimed ATOMICALLY
before the 76s sweep (`kv_store.put_if_absent` — new primitive; INSERT ON
CONFLICT DO NOTHING); the loser walks away; a failed sweep releases the claim
so the day retries. Accuracy history: idempotent last-wins append (one row
per date, structurally) + journaled one-off `dedupe_accuracy_history()` for
the doubled 08-07/08-08 rows — LIVE RUN post-deploy (artifact 08). Tests:
`tests/test_hardening_wave.py` (4 F16 tests).

**F12 · Reflected XSS via ?roster= — CLEARED (adversarially re-run).**
Client-side whitelist (VALID_LEVELS/VALID_METRICS) fires BEFORE any render;
esc() on the URL-derived metric in the drill title; server 400s crafted
metrics without echo. In the standing taint-regression set:
`tests/test_xss_roster.py` (4) + the L3 sentinel replays the probe weekly.

**F7 · Contact-merge reached droop — CLEARED.** The reached sweep prunes
cached evidence ids no longer present in the contact table (journaled, epoch
bump) — the re-check happens the SAME sweep; a dead contact pull never reads
as "all merged away" (guarded). Tests: `tests/test_polish_wave.py` (2).

## SEV4 — polish

**F10 · Journal-crash gap — CLEARED.** Journal-FIRST ordering in
record_derived_date + supersede_derived: a crash leaves a journaled-but-
unapplied entry (detectable, re-runnable), never a silent derivation.
Tests: `tests/test_polish_wave.py` (2).
**F11 · Immortal invisible orphan derivations — CLEARED.** Nightly orphan
census (derivations whose tracker row is gone) → visible sweep bucket + feed
flag; inert, never auto-deleted (excluded ≠ deleted). Test:
`tests/test_polish_wave.py::test_orphan_derivations_are_counted_and_flagged`.
**F14 · Doc drift — CLEARED.** ads.py docstring corrected (notes cap = first
8, not ≤30); AD_DASHBOARD_REPORT.md carries a SUPERSEDED header pointing at
roster_engine + ADS_SYSTEM_STATE.md.
**F15 · verified-show-ratio decline unwatched — CLEARED.** The ratio is a
TRACKED sentinel metric: L1's delta-anomaly band alerts on decline (>0.03
hour-over-hour) and L2's drift diff on night-over-night worsening. Tests:
`tests/test_sentinel.py::test_vsr_decline_is_watched_and_alerts` +
drift-diff coverage.

## RULING R1 · Refund semantics — ENCODED (DECISIONS #132)

Kept as-is per Rydel: the payment cleared → the deal closed; a refund is
post-close economics. Shipped with the ruling: `cash_truth.refund_report()`
— the lane the refund MOVES TO (includes fully-refunded charges the cash
view rightly drops at $0), riding `unified_cash_view.refunds`. Tests:
`tests/test_refund_ruling.py` (4 — derived close date survives a full
refund; the refund is visible, not vanished; cash view stays clean; Stripe-
dead degrades to None).

## PHASE H — THE SENTINEL (SHIPPED)

`ad_sentinel.py` + wiring (app.py boot, ads_truth L2 cost block). L0 inline
(the registered write/compute guards, surfaced via kv, read by L1) · L1
hourly (recon + I10 partition + I17 n=5 + delta-anomaly band incl. F15) ·
L2 nightly (the sweep, now self-timing with a SENTINEL COST block in its
accuracy row + drift diff + the heal pass) · L3 weekly (full I17 · full 90d
quad-check · 5-claim re-proof · security replay incl. /debug 401 + taint 400
· perf regression). ESCALATION: targeted domain pass per signal — spend
follows signal. SELF-HEAL: deterministic data-layer only (rollup rebuild ·
cache clear · contact re-sync · resolve_dates · test-skeleton), journaled to
the durable evidence stream + one quiet feed line each. KILL SWITCH:
`AD_SENTINEL_PAUSE_HEALS` pauses heals, detection continues (proven).
Budgets per layer; breach = LOUD; cost rows auditable (kv sentinel:cost).
Queue: SENTINEL_QUEUE.md (seeded). Proof pack: `tests/test_sentinel.py`
(11 — every layer ran, forced escalation, forced sandbox heal, kill-switch
demo, budget breach, F15 alert).

## PROVEN-GOOD (unchanged from discovery, re-verified by the wave's suite)

First-touch ownership (B3) · I17 two-deals-one-identity (B2) · dedupe class
(B2b) · hybrid keying (B4) · window boundaries (B8) · cancel-rebook (B12) ·
USD/partials (B7) · supersession surfacing · auth walls · media_buyer
disabled · sweep-failure loudness.

## GATE-CLOSE ADVERSARIAL REVIEW PASS (2026-08-09, pre-ship)

An independent adversarial review of the fix-wave diff verified 9 findings —
ALL FIXED BEFORE SHIP (tests: `tests/test_review_fixes.py`, 8):
R-1 refund leg's second pull clobbered the partial marker → snapshot-after-
own-pull semantics (the view reports ITS pull's state) · R-2 F9 guards checked
the marker BEFORE the pull they guarded → post-pull re-checks in the ruling
pass + card builder · R-3 Stripe charge dates sliced the server-local day →
explicit Sydney-day conversion + the F8 migration extended to derived:stripe
provenance (fetch-by-charge-id) · R-4 the F7 prune was a no-op (attr_contacts
never tombstoned) → complete syncs now tombstone absent rows (reversible) ·
R-5 the sentinel's security replay flipped the LIVE app into TESTING mode →
removed · R-6 cache-prune dict-iteration race → snapshot iteration ·
R-7 orphan census could mislabel dotted-name derivations (norm split) →
dual-norm check · R-8 nav_router probed a dead 2-tuple cache key → cache_fresh
· R-9 claims: fail-closed on DB errors + stale mid-sweep claims reclaimed
after 2h.

**F17 · OPEN (NEW, found by the review): normalization split between
`resolution._norm` (strips '@'/'.') and the engine's `_norm` (keeps them).**
Derived-store keys for names containing '.' or '@' can never match an engine
name_norm — the derived-date MERGE silently skips them (pre-existing; distinct
from the census mislabel, which is fixed). Not fixed blind in this wave:
changing either norm rewrites identity keys across the derived store, spine
events, and reached cache — needs its own careful session with a keyed
migration. Queued (SENTINEL_QUEUE P1); live blast radius to be measured
post-deploy (count derived keys containing '.'/'@' vs tracker).
