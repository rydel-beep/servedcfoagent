# AD-SPEND CONSUMER FIX — one live source dashboard-wide

**Date:** 2026-06-24 (Sydney) · **Scope:** served-cfo-agent only. The Meta build wired live spend
into CAC/LTGP:CAC/ROAS but left other consumers on the stale Xero line / $8,002 fallback. This
repoints EVERY consumer to the single resolved live-Meta source.

## Phase 0 — full ad-spend consumer map (live)

Xero is now connected (Rydel completed `/xero/connect`), so the stale figure was the **Xero
Advertising line = $7,384.28** (trailing 30d); the old `$8,002` hardcode was the pre-Xero fallback.
Live Meta 30d = **$9,041**.

| Consumer | File | Old source | Status before |
|---|---|---|---|
| CAC / LTGP:CAC / ROAS / LTV:CAC / payback | `hormozi_metrics.py` | `ad_spend_resolved` (Meta) | ✓ correct |
| Economics tab | `dashboard.js` renderMonthPerformance | reads hormozi | ✓ correct |
| Lead-Source ROI cost/close | `dashboard.js` renderLeadSourceROI | `ad_spend_resolved` | ✓ correct |
| **Profit Waterfall** (OpEx breakdown) | `dashboard.js` renderWaterfall | `xero.xero_ad_spend` ($7,384) | ✗ stale |
| **Cash burn breakdown** | `dashboard.js` (burn.ad_spend) ← `opex_pull.get_monthly_burn` | Xero line / $8,002 fallback | ✗ stale |
| **Financial position** (cash net) | `financial_position.py` ← snapshot | burn/Xero ($7,384) | ✗ stale |
| **Verdicts** (cost-per-lead leak) | `verdicts.py` | `xero.xero_ad_spend` | ✗ stale |
| **Briefing PDF** burn line (3rd consumer found) | `briefing_pdf.py` | `burn.ad_spend` (Xero/$8,002) | ✗ stale |

Single source the Meta build created: `snapshot.ad_spend_resolved` (Meta live → Xero line → None),
read by hormozi via `_resolved_ad_spend`. Why the others missed it: the burn was computed in
`opex_pull` from the Xero P&L *before* the resolution existed, the waterfall/verdicts read
`xero.xero_ad_spend` directly, and the PDF read `burn.ad_spend` — none routed through the resolver.

## Phase 1 — repoint everything to ONE source (window-matched)

- **Resolution moved up:** `snapshot._resolve_ad_spend(meta_block, xero_line)` is computed **before**
  `get_monthly_burn` and passed into it as `ad_spend_override`. Burn, financial_position, hormozi,
  waterfall, verdicts, and the PDF now all read the identical resolved value. 30d window everywhere
  (waterfall period = "trailing 30d", burn = monthly, funnel/CAC = 30d → all match Meta's 30d
  primary). Each consumer's window is the trailing-30d that Meta's primary window covers.
- **Burn (`opex_pull.get_monthly_burn`):** new `ad_spend_override` REPLACES the Xero advertising
  line; the Xero line is retained as `ad_spend_xero_ref` for cross-reference. Burn total reflects the
  override (live Meta).
- **Waterfall (`renderWaterfall`):** Ad Spend breakdown now shows the resolved figure, sub relabelled
  "Meta (live, 30d)". The P&L **headline** (Revenue/COGS/Gross Profit/OpEx/Net) stays **Xero-sourced
  and reconciled** — only the OpEx *breakdown attribution* shows live ad spend; "Other OpEx" (already
  a residual plug) absorbs the Xero-vs-Meta variance, so the components still sum to Xero OpEx.
- **Verdicts / PDF / financial_position:** read the resolved value.
- **Dead source killed:** `AD_SPEND_FALLBACK = 8002.0` REMOVED. With no Meta and no Xero, burn ad
  spend = **0 with a loud note** ("Ad spend unavailable… burn excludes ad spend"), never a hardcoded
  guess. Any fallback is the labelled Xero line or labelled Meta last-known — surfaced, never silent.
- **Retroactive/freshness** behaviour from the Meta build now applies to every consumer (one engine).

## Phase 2 — cross-section consistency (acceptance gate)

Live build, 30d window — every consumer reads the **identical** figure:

```
RESOLVED (ad_spend_resolved.value): 9041.62   source: meta_live
Meta 30d window:                    9041.62
Burn breakdown (burn.ad_spend):     9041.62
CAC inputs (cac_loaded):            9041.62
LTGP:CAC inputs:                    9041.62
ROAS inputs:                        9041.62
financial_position.costs.ad_spend:  9041.62
ALL EQUAL? True  →  {9041.62}
Xero line (cross-ref, differs by design): $7,384  (kept as ad_spend_xero_ref)
```

**Before → after per repointed consumer:**

| Consumer | Before (stale) | After (live Meta 30d) |
|---|---|---|
| Profit Waterfall — Ad Spend | $7,384 (Xero line) | **$9,041** (Meta) |
| Cash burn breakdown — Ad | $7,384 / $8,002 fallback | **$9,041** |
| Financial position — ad spend | $7,384 | **$9,041** |
| Verdicts cost-per-lead | based on $7,384 | based on **$9,041** |
| Briefing PDF — Ad spend | $7,384 / $8,002 | **$9,041** |

**Dependent figures recompute:** burn total rises by the $9,041−$7,384 = ~$1,657 ad-spend delta;
financial_position cash-net drops by the same; the waterfall's Net Profit is unchanged (it's Xero's
actual net — only the OpEx attribution detail changed). The delta is the live Meta spend exceeding
what Xero had booked (Meta platform spend leads the Xero GL booking).

**Non-regression:** CAC/LTGP:CAC/ROAS unchanged (already on Meta); 215 tests pass (+2 burn-override,
+1 no-override-excludes); Meta integration, data-accuracy fixes intact.

## One source, going forward
`snapshot._resolve_ad_spend` is the only place ad spend is resolved. Google Ads slots in here (sum +
relabel blended). The Xero advertising line survives only as a labelled cross-reference
(`ad_spend_xero_ref`), never as a headline figure.
