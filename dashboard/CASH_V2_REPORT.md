# Cash V2 — Full-Outflow Burn + Dual Deployable Cash + True Runway

## The Problem
Monthly burn was showing $29,671 (team cost only), giving a 4.7-month runway. This excluded
ad spend (~$8k), delivery COGS (~$10k), subscriptions, and other opex. Real burn is $49,213/mo
and real runway is 2.8 months — a material difference for hiring and deployment decisions.

## Full-Outflow Burn Breakdown (trailing 30d from Xero)

| Category | Amount | Source |
|---|---|---|
| Team (fixed) | $29,671 | SALARY tab |
| Ad spend | $8,002 | Xero Advertising |
| COGS delivery | $10,341 | Client Tools $7,769 + subcontractors $1,236 + videog/photog $1,336 |
| Subscriptions | $382 | Subs $228 + Telecom $154 |
| Other opex | $817 | Consulting $179 + Bank fees $605 + Office $33 |
| **Total recurring burn** | **$49,213** | |

**Excluded from forward burn:**
- Commissions: $7,421 (variable, in CAC layer)
- One-offs: $4,044 (travel $3,049 + consulting one-off $995)

## Runway Correction
- **Old (team-only):** $140,007 / $29,671 = 4.7 months
- **New (full burn):** $140,007 / $49,213 = **2.8 months**

## Dual Deployable Cash
- **Aggressive war chest:** $120,007 (cash $140k − tax reserve $20k)
  - Treats all upfront cash as available — optimistic
- **Conservative war chest:** $113,707 (also excludes delivery reserve $6,300)
  - Delivery reserve = Stripe incoming $18k × COGS ratio 35%
  - The cost to deliver work already paid for
- **COGS ratio:** 35.0% (Xero: COGS $27,895 / Revenue $79,708)

## Triple-Check Results
1. **Arithmetic:** Manual calculation matches code output ($49,213) ✓
2. **Directional:** Full burn > team-only; full runway < team-only; conservative < aggressive ✓
3. **Cross-source:** Every line traces to Xero account or SALARY tab ✓

## Architecture
- `opex_pull.py` — modular interface (`get_monthly_burn()`), swappable to Google Sheet later
- `xero_pull.py` — now extracts per-line items from COGS and OpEx sections
- `snapshot.py` — `monthly_burn` block + enhanced `cash_position` with dual deployable
- `hiring_model.py` — uses total burn (not team-only) for forward sustainability
- `dashboard.js` — burn breakdown display, dual war chest, runway on total burn
- `chat.py` — Jarvis gets burn breakdown and dual deployable context

## Files Changed
- `xero_pull.py` — added `_extract_section_lines()`, `cogs_line_items`/`opex_line_items`
- `opex_pull.py` — NEW, categorised burn from Xero P&L
- `snapshot.py` — `monthly_burn` block, enhanced `cash_position`
- `hiring_model.py` — accepts `total_monthly_burn`, uses it in forward lens
- `dashboard/routes.py` — passes `total_monthly_burn`
- `dashboard/static/js/dashboard.js` — full burn breakdown, dual deployable, true runway
- `dashboard/chat.py` — burn breakdown in Jarvis context
- `tests/test_opex_pull.py` — 10 new tests (88 total passing)
