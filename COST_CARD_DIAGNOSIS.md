# COST CARD DIAGNOSIS — the /scale cost card vs the revenue card (2026-09-24)

Phase 0 of "the cost card, made true". Every line on both cards traced to its
formula, its inputs, and each input's provenance. The witnessed state is
Rydel's 24 Sep read: spend $22,500 · CPL $55 → 409 leads · 18% → 75 calls ·
90% → 67 · 28% → 18.7 clients; revenue $85,033 / $289,227 / +$48,204;
cost $2,444 all-in · 2.71× · commissions $16,911 · bounties $3,747 ·
fixed $500 · tooling $2,132.

## Where the numbers are made

Three copies of one formula set, parity-tested against each other:

- `compass_engine.simulate_month()` (compass_engine.py:1369) — the server's
  single-month chain; server-renders the first paint of both cards.
- `dashboard/static/js/sim_core.js` `chain()` — the browser's instant
  recompute; the 200-set node parity test pins it to the engine.
- `compass_engine.forward()` (compass_engine.py:590) — the month-by-month
  roadmap; `simulate_month` is identity-tested to its first month.

## The revenue card ("What do they pay us?") — line by line

| line | formula | inputs and provenance |
|---|---|---|
| cash this month | `clients × m0_share × contract_mix` | `m0_share` = mix-weighted month-0 share of each package's measured cash schedule (`_package_economics`: month-0 share measured from 90d closes' cash÷contract, blended across packages); `contract_mix` = Σ deal_mix[p] × packages[p].contract (MRR = active-book median per package, term = config `PACKAGE_TERMS`) |
| over the term | `clients × contract_mix` | same mix, same packages |
| +$/mo revenue | `clients × mrr_mix` | same mix, package MRR |

The mix here is **`inp["deal_mix"]`** — a MEASURED default (tracker offer
column on 180d won rows, `measured_defaults` compass_engine.py:176), and it
is editable in the advanced panel. This is the correct shape.

## The cost card ("What does it cost us?") — line by line, witnessed arithmetic

| line | witnessed | formula | where it comes from |
|---|---|---|---|
| ad spend | $22,500 | `S` | the spend input |
| commissions on closes | $16,911 | `comm_per_close × clients` = $902.50 × 18.74 | `_modelled_comm` → `sales_cost.modelled_commission` with **`inp.get("package_mix") or None` → `{growth_pro: 1.0}`** and **`inp.get("closer_mix") or {"kalin": 1.0}`**; $902.50 = $750 Kalin GP flat + 5% × $3,050 (a **hardcoded** `first_month_cash_ex_gst=3050.0` default parameter) |
| set bounties | $3,747 | `$50 × calls` = $50 × 74.9 | rulebook `per_set`, applied to **every booked call** |
| manager retainer + bonuses | $500 | `monthly_fixed.total` | Kalin's $500 retainer; Coby's $350 KPI bonus is coded but **only fires when a junior is in the closer mix — which the default mix never has**; the $1,000 fast-win bonus is **not modelled anywhere** |
| sales tooling | $2,132 | `SALES_TOOLING_MONTHLY` | config env, itemised GHL ~$580 + A-Leads $1,500 + Instantly $13 + ManyChat $39 — **flat regardless of volume or seats** |
| per client all-in $2,444 | | `(S + comm + bounties + fixed + tooling) / clients` | = $45,790 / 18.74 ✓ |
| profit-vs-cost 2.71× | | `(contract_mix × margin_mix) / cac` | margin_mix = FY26 42.9% on every package (`FY26_MARGIN_PCT`) — **the ratio is LTGP:CAC on term gross profit and neither the name nor the margin's source renders** |

## D1 — WHERE THE TWO CARDS DIVERGE (confirmed)

**The revenue card runs on `deal_mix` (measured, mix of real packages). The
commission engine runs on `package_mix` — a DIFFERENT KEY that no measured
default, no `default_inputs()` entry, and no UI control ever sets.** So it
silently falls to `modelled_commission`'s fallback `{growth_pro: 1.0}`,
`{kalin: 1.0}`, with a hardcoded $3,050 event cash — every deal a Kalin
Growth Pro, exactly the witnessed $902.50 × 18.74 = $16,911, while the
revenue card's $4,533-per-client month is the measured mix × the measured
schedules. The term figure agrees with neither being "wrong" alone — the two
cards simply consume different mixes. `DEFAULT_MIX` in sales_cost.py even has
a THIRD answer (50/50 GP/SE) that the compass path never reaches because it
passes `package_mix: None` which overrides it.

Bonus defect found on the way: `modelled_commission`'s PIF handling reads
`ev_cash = scale_cash if pif else scale_cash/2` — **any non-zero `pif_share`
(default 0.5) is treated as 100% PIF**. The share is never weighted.

## D2 — CONTRADICTORY PROVENANCE (confirmed)

Template footnote (scale.html:166): "commissions on the sales-comp rulebook
(v4) — $902 a close…". Registry entry `chain_cost.default_from`
(dashboard/definitions.json:737): **"commissions use last year's actual 6.3%
of sales."** Both render on the same card (footnote + tooltip/legend). The
registry copy predates #159 and was never updated. The advanced inputs panel
still carries a live control "commissions (% of new cash)" (scale.js:41)
bound to `commission_pct_of_cash`, which nothing in the cost path consumes
any more (forward() line 606 assigns it and never uses it; simulate_month
returns it as `comm_rate` purely as the client's stale-payload fallback).

## D3 — BOUNTY BASIS (confirmed)

`bounties = comm["bounty_per_set"] × calls` (compass_engine.py:1408) — $50 on
every **booked call**. Rulebook v4: "$50 per **qualified** set"
(`set_fee_basis: "qualified"`). The chain has no qualified stage. The ONE
qualification rule exists (`attribution_engine.qualify_lead`, Rydel v2:
not disqualified · revenue ≥ floor · revenue answered) and the tracker rows
carry everything it needs — it is simply not wired to the simulator.

## D4 — NO CLOSER MIX (confirmed)

`closer_mix` is accepted by `modelled_commission` (the junior table exists
and is correct: Coby GP $550 / SE $1,000 as the COMPANY TOTAL, Kalin's 3%
carved out inside), but no measured default computes it, `default_inputs()`
does not carry it, and no UI can set it. The engine-side capability shipped
in #159; the input plumbing never did. Tracker won rows carry `closer` and
`setter` cells (attribution_engine idx), so it is measurable. GHL opportunity
`assigned_to` is mirrored (ghl_mirror) but holds an unmapped user id — noted
as corroboration-pending, not a source.

## D5 — MISSING BONUSES (confirmed)

`monthly_fixed` = $500 retainer + ($350 KPI **iff** a junior is in the
closer mix). Because of D4 the mix never contains Coby, so the KPI bonus can
never appear. The $1,000 fast-win at 10 lifetime closes exists only as data
in the rulebook (`junior_extras.fast_win_bonus`) — no engine reads it.

## D6 — NO CAPACITY COST (confirmed, both levels)

`forward()` HAS a capacity model: utilisation per role, auto-hire cards
dated `hire_lead_weeks` back, `hire_cost` charged into the cash position
from the start month (compass_engine.py:741-745). But:
- its period CAC is `spend + commissions + tooling` (line 768) — hire cost
  deliberately excluded with the comment "sales-role hires would move this";
- its cohort CAC likewise;
- `simulate_month` — the card Rydel actually reads — has **no capacity terms
  at all**. At the witnessed volume (409 leads, 75 calls) the model's own
  throughputs (175 leads/setter, 60 calls/closer) say 3 setters and 2
  closers; the team snapshot says 2 setters, 1 closer. The card shows $0 for
  the gap, so CAC is flat at any spend.

## D7 — TOOLING FLAT (confirmed)

`SALES_TOOLING_MONTHLY = 2132` config; one number regardless of volume or
seats. The outflow/tooling classification (outflow bands / FIXED COSTS tab)
records the subscriptions as account-level totals — the books do NOT record
a per-seat price for any of the four tools. So a measured per-seat split is
not available; what is possible honestly is a fixed base plus an explicit
per-seat input defaulting to 0 ("needs your number"), scaling with sales
headcount, labelled.

## D8 — UNNAMED RATIO (confirmed)

The card prints "profit-vs-cost 2.71×". It is LTGP:CAC — mix-weighted
contract × 42.9% FY26 margin ÷ all-in CAC. The finance tiles' definitions
(`hormozi_metrics`): LTV:CAC = full avg contract ÷ loaded CAC (no margin);
LTGP:CAC = margin-bearing. Neither name, nor the margin figure, nor its
source (FY26 fallback vs package delivery cost) renders on the card.
"Show the math" (scale.js:317-331) also under-prints the CAC line: it shows
`(ads + commissions + tools) ÷ clients` — omitting the bounties and the
fixed costs it actually charges — and shows no mix weights anywhere.

## The capacity/hiring model and the compass wiring (asked directly)

It exists (`forward()` in-engine: THROUGHPUT_DEFAULTS, ROLE_COSTS_MONTHLY,
RAMP_WEEKS, auto-hire cards, utilisation, binding constraints; team_view
renders it). The cost card is **not wired to it** — no headcount line, no
hire cost in any CAC anywhere.

## Where the stale 6.3% copy is generated

1. `dashboard/definitions.json` `entries.chain_cost.default_from` (the one
   Rydel saw as the second footnote sentence);
2. the live-but-unconsumed "commissions (% of new cash)" control
   (scale.js CTLS) with its `commission_pct_of_cash` measured-default item
   whose provenance text reads as if the rate were still the source.
   (`config.FY26_COMMISSIONS_PCT_OF_SALES` itself is a legitimate sanity
   anchor and stays — as a labelled reference only.)

## What the fix must therefore be (the brief's parts, confirmed applicable)

1. ONE mix: `closer_mix` + `setter_mix` (+ `pif_share`, `qualified_rate`)
   measured into `measured_defaults`; commissions derived from the SAME
   `deal_mix` and the SAME package schedules that price the revenue card;
   invariant tested; explicit `package_mix` overrides warn when they diverge.
2. Commissions rulebook-only; event cash per package from the package
   economics (ex-GST per R-GST), PIF share weighted (bug above); fast-win
   modelled; FY26 6.3% demoted to a labelled reference beside; registry copy
   and the dead % control replaced.
3. Qualified rate input (measured through `qualify_lead` on 90d set rows;
   payout-log evidence as fallback), bounties on qualified sets.
4. Capacity wired into the card and into every CAC: headcount needed at the
   modelled volume vs today's team, costed (config role costs, labelled),
   dated by hire lead time; fixed-vs-variable labels per line.
5. Tooling = fixed base + per-seat×seats with per-seat defaulting 0 and
   labelled "the books don't itemise per-seat — needs your number".
6. Ratios named with margin source; show-the-math prints every line's real
   arithmetic including mix weights.
