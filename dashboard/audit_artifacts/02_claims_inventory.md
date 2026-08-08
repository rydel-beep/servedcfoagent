# Phase A — Claims inventory + fresh re-verification (2026-08-08)

Every claim re-proven by fresh evidence TODAY or marked otherwise. Sources:
DECISIONS #111–#131, dashboard/*_REPORT.md, *_DIAGNOSIS.md, session notes.

| # | Claim (source) | Verdict | Fresh evidence |
|---|---|---|---|
| C1 | Nightly truth sweep runs (many docs) | **PROVEN (with caveat)** | `start_loop()` wired in app.py:834 (6h loop, kv-stamped daily); tick=2026-08-08; accuracy rows 08-07/08-08 (artifact 00). CAVEAT: history only exists since 08-07 (feature age) — continuity unprovable beyond 2 days, and the loop sleeps 6h BEFORE first tick (a crash-looping worker would never tick; boot does not tick immediately). |
| C2 | Railway build gate enforces compileall+import (#112) | **PROVEN** | railway.json buildCommand verbatim. |
| C3 | Suite green — 684 tests (roster session) | **PROVEN** | Fresh run: 684 passed (artifact 01). |
| C4 | Xero scopes not landed / 401 (show-truth, #131) | **PROVEN** | Server-side probe today: Invoices 401 (prior mission Phase 0). |
| C5 | GHL payments endpoints 401-scoped (#131) | **PROVEN** | /payments/orders, /payments/transactions, /invoices all 401 with live token (prior mission D3, artifact in ROSTER_DIAGNOSIS). |
| C6 | 97.3% contact→tracker identity (hygiene header) | **PROVEN** | Re-measured live: 89.9% email-ID + 7.4% name-unique = 97.3% (1,114 rows). |
| C7 | Spine census 18/18 T1, 0 phantom (ads-truth) | **PROVEN** | Accuracy rows: T1=18, T0=0 (artifact 00). |
| C8 | Reached sweep incremental + cached (#126) | **PROVEN** | kv: 22 positive, 98 swept-none, caches bounded (84 appt / 21 call < 800 cap). |
| C9 | 35 set + 19 show dates derived (#128 session) | **PROVEN (identity, grown)** | Store today: 37 set_date, 21 show_date, 4 input_date — nightly increments explain drift; provenance derived:ghl-appt=58. |
| C10 | 10 ruling conversions, $30,983, idempotent (#131) | **PROVEN** | Journal entries + charge ids + convert-twice no-op re-run (prior mission artifacts, re-checked in 00: close_date=10, derived:stripe=10). |
| C11 | I17 zero drift, 18,744 cells (roster session) | **PROVEN** | Live sweep run today; nightly sample {checked:20, drift:0} in tonight-equivalent sweep run. |
| C12 | I15 market partition / I16 view purity test-enforced (#127) | **PROVEN** | Named tests present (tests/test_ads_ux.py, 4 partition matches; I16 grep test in test_ads_ux). |
| C13 | derived_placed recon terms test-enforced (#128) | **PROVEN** | tests/test_funnel_completion.py + live recon: engine 58 = canonical 48 + derived 10, ok=true. |
| C14 | media_buyer SHIPS DISABLED (ads.py header) | **PROVEN** | Live env: no MEDIA_BUYER* var (names-only probe); auth.py gates account creation on the var. |
| C15 | Sweep failure is LOUD (ads-truth) | **PROVEN** | test_sweep_failure_is_loud in fresh suite run (artifact 01). |
| C16 | Verified-show ratio in accuracy row (#129) | **PROVEN** | Rows carry 0.9 → 0.857 (NOTE: it FELL — new status-only shows derived nightly outpace verification; not a bug, but nobody is watching the trend → sentinel item). |
| C17 | "GHL notes ≤30 contacts throttled" (ads.py docstring) | **DISPROVEN (doc drift)** | Code caps at 8 (`contact_ids[:8]`, ads.py:295). Behavior fine; the DOC lies. → register F13. |
| C18 | "roster length == count structurally enforced" (old ads.py docstring, pre-roster-engine reports) | **SUPERSEDED-TRUE** | Now stronger: I17 members at increment + build check + nightly sample. Old docs describe a dead mechanism — noted in ADS_SYSTEM_STATE as historical. |
| C19 | Journal = "the log IS the trust" (resolution.py) | **AT RISK** | Log capped at 200; oldest surviving entry is 2026-08-07 — evidence horizon ≈ 2 days. Ruling-conversion evidence will age out. → register F2. |
| C20 | A5 self-retiring flags (resolution doctrine) | **PARTIALLY DISPROVEN** | `integrity:pending` holds 15 stale `invariant:*` entries from past transient states; only phantom entries are pruned. Current invariants all-ok yet the queue still lists them. → register F3. |
| C21 | Accuracy quad-check "every close ≤90d" | **PROVEN** | facts_checked=24 ≈ 18 closes + annotations; agreements 18, 1 standing disagreement (tracker_hygiene, named). |
| C22 | Drill/roster <500ms budget (UX报告 + roster session) | **DISPROVEN as stated** | Warm-cache path 210–230ms ✓, but cache TTL 30min × per-worker × per-(basis,days,market) key → common case is COLD ≈ 5.7–7.4s measured (artifact 00 latencies). The budget holds only in the minority path. → register F1. |
