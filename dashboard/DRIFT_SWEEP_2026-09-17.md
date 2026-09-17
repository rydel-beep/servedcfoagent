# DRIFT SWEEP — 2026-09-17 (a month of no eyes)

Register: FIXED (deterministic) or FLAGGED (judgment), evidence beside each.
SEV1 = act now · SEV2 = this week · SEV3 = at leisure.

## FIXED this run (deterministic, journaled, test-pinned)

| # | What | Evidence |
|---|---|---|
| F1 | **MRR snapshot cadence** — boot-only → daily via the 2h refresh loop; null-row guard; today's null/0 row self-healed to **$72,887.52 / 38 clients** | `mrr_snapshots` 2026-09-17 row |
| F2 | **GHL contacts mirror dead since 07-27** — daily kv-claimed contacts/notes pass added to the sync loop | `ghl_sync_state` post-deploy |
| F3 | **Watchdog-of-the-watchdog** — sentinel/sweep/L2 now registry subjects; FAILING/STALE `cfo:*` rows publish LOUD self-retiring feed items; L1 watches the snapshot loop back. Drill proven: dead sweep → 3 feed items | drill transcript in the session note |
| F4 | **Three gap closes derived** into the one engine (sanctioned lane, evidence ids, epoch bumped): Orlando Rinaldi 09-09, William Cooney 09-11, Harman Singh 09-11 | `derived:dates` + gap:journal |
| F5 | Projection month-0 re-proved EXACT: committed == recognized-now == roster **$72,887.52**, drift 0.0 | `forward_projection.project()` recon |
| F6 | Renewal sheet scan run: **clean, no changes, no conflicts, no schema drift** | scan verdict 2026-09-17 |
| F7 | Three date-rotted/live-data tests fixed so the suite gates deploys again (footer test now asserts surfaced-not-clean) | suite 1084 green |

## FLAGGED (judgment / human action — SEV-ranked)

| SEV | What | Owner |
|---|---|---|
| 1 | **Tracker backfill package — 11 rows** (6 close rows incl. 3 PROPOSED needing payment evidence: Kristeen Hammond 07-31, Michael Pulvirenti 08-27, Jay Lunsford 09-16 US; 5 gap-window leads missing from the tracker). Live in the Piolo queue; items self-retire as the mirror sees cells land. READ-ONLY law: the agent never writes the sheet | Piolo (rows) · Rydel (PROPOSED calls) |
| 1 | **Harman Singh has NO client row anywhere** (no tracker row, no Health-tab row) despite a $3,355 Growth Pro-pattern payment (`ch_3UFOCz…`). Venue + contract value unknown — blank ≠ zero | Rydel names the venue → Piolo rows it |
| 1 | **Recognized-revenue footer mismatch**: rows sum $76,437.52 vs footer $67,337.52 — the sheet's own footer is stale | Piolo |
| 1 | **6 won deals not on the Health tab** (The Vault, Texas Charcoal Chicken, Butlers cucina, Il Ritrovo, Gone Burger, Alice Springs Brewing Co) — MRR understated ~$12,450/mo; + **6 Active clients at $0 MRR** (3 Fish, Masala Factory, Naan Sense Indian, Firefly Espresso Bar, At Thai, Pottery Green Bakers) — possibly churned, sheet not updated | Piolo + Rydel |
| 2 | **R-A2 review cadence never ran** — zero review sessions since the 08-24 migration; the due-cohort ages on the board | Rydel + ad team |
| 2 | **62% of 7d ad spend on UNMAPPED sets** ($2,073.59 of $3,356.78): SVIT Ad Set 2 $665 · Whole USA $434 · T&F USA $404 · **Served Graphic Interests Targ $395 (the obvious `graphics` role)** · **Retargeting Ad Set 1 $111 (the obvious `retargeting` role)** · FB&IG Followers $64. Mapping = owner action in the /ads strategy panel (ids-are-truth, journaled). The two US sets are a NEW campaign — Rydel's read | Rydel |
| 2 | **Cash-needs-logging: 7 deals** with Stripe ahead of tracker cash (Cyrus Platon +$2,250.90 · Food Corp +$1,650 · Akuna +$1,650 · Ashley Clarke +$255 · Christina Theravanish +$255 · shalini bhargava +$168.90 · Tommy Sun +$135) + **4 unmatched payments** (Fiona FITZGERALD $5,500 09-09 — Glen Fitzgerald's payer? · NIROSHA $1,678 · Allan Thai $3,355 · Pottery Green Bakers $1,760) | Piolo / sales team |
| 2 | **GHL hygiene** (flag for the GHL owner — READ-ONLY law, agent never re-stages): 56 Closed-Deal-stage opps still status `open`; Arthur Gruselle closed via Stripe 08-10 but his GHL stage never moved | Rydel/Tristan |
| 3 | Access roster: creds live for rydel · piolo · romano · isaiah · inna (SALES never enabled). Last logins: piolo 07-22 · rydel 08-10 · isaiah 08-10 · inna 08-10 · romano 08-13. No departures known to the agent — revocation = Rydel deleting the env var | Rydel |
| 3 | `forecasting_engine.record_projection` has zero production callers (accuracy loop is dead code) — wire or remove next session | agent |
| 3 | Loudness residual: if BOTH loops die simultaneously, the last signal is Railway /health — external uptime alerting (or a Lark push when the feed goes red) is Rydel's call | Rydel |
| 3 | Stripe-MCP service still ignores `days` + returns unknown customer counts (standing degraded items `revenue_previous` / `customer_count`) — service-level, tracked since 08-14 | Rydel (MCP service) |

## Re-proofs run green
- I17/reconciliation: nightly sweep green all month, last night included;
  attribution recon `all_ok` on the 90d probe.
- Meta archive completeness: no missing recent days (nightly check green).
- Stripe canary green; BAS estimate current (09-16); outflow bands current
  to August close (September restates at month-end as designed).
- EDITH memory maintenance ran nightly (last 09-16); convo-quality weekly
  ran 09-13.
- DECISIONS current: #148 (read-only law) + #149 (R-GAP/R-CASH/R-ROAS)
  logged with the detected window 2026-07-24 → open.
