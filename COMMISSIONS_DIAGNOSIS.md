# COMMISSIONS — PHASE 0 DIAGNOSIS

**2026-09-22 · read-only · production `34aa5d9`**

Rydel asked for accurate setter and closer commissions "at least as an
average — so as we scale we have a clear picture of CAC and what it costs
us apart from ad spend." This is what the estate actually computes today,
proved with numbers before a line of it was changed.

---

## 1 · THE VERDICT

**The hypothesis is confirmed, and it is worse than stated.** The brief
supposed commissions were *understated* because the tracker's commission
cells are blank for gap-window closes. They are not understated. For the
September cohort they are **exactly zero**, on every surface, and the whole
visible difference between loaded and spend-only CAC is sales tooling.

| September cohort (1–21 Sep), live | value |
|---|---|
| ad spend | **$9,112.28** |
| closer commission, as computed | **$0.00** |
| setter commission, as computed | **$0.00** |
| sales tooling, window share | **$1,470.83** ($2,132 × 21 ÷ 30.44) |
| closes, standing engine | **0** |
| closes, as rendered on the tile | **3** (substituted from the union engine) |
| CAC fully loaded | **$3,525.03** |
| CAC spend only | **$3,034.75** |
| **the difference the tile shows** | **$490.28 per close — tooling, and nothing else** |

Under the ruled structure the same three closes should carry roughly
**$750–$950 each** in commission. The tile is not showing a small
understatement; it is showing none of it.

`snapshot.costs` agrees, and it is what the Hormozi metrics read:

```
{'closer_commission': 0.0, 'setter_commission': 0.0,
 'source': 'sheet actuals (Commission Closer #20, Commission Setter #19)'}
```

### Why zero

- **The tracker has recorded no won deal since 2026-07-20.** Not "blank
  commission cells on recorded closes" — no closed rows at all for August or
  September. Summing a column over zero rows gives zero, and the code reads
  that zero as a fact.
- **The setter path windows by PAYOUT date**, and only **42 of the 194**
  payout-log rows carry one (all June–August). September has no payout date,
  so September has no setter cost.

### The extra defect nobody asked about

The commission numerator and the close denominator come from **different
populations**. `range_unit_economics` sums commissions over a window in which
its own engine finds **0 closes**; the tile then divides by **3** closes taken
from the union engine (the drawer says so: *"closes from the union engine
(n=3; tracker won-marks lag — the gap-window class); components from the
standing engine"*). Even once commissions are non-zero, a per-close figure
built this way is summing over one set of deals and dividing by another.

---

## 2 · EVERY COMMISSION PATH FOUND

Seven, of which **four independently compute a number**. This is the
one-engine violation, and the paths cannot agree by construction — some are
dollar sums per deal, one is a percentage of cash.

| # | path | method | live value |
|---|---|---|---|
| 1 | `range_unit_economics._ltc_in_window` | sums the tracker's *Commission Closer* cell for won rows closed in window | **$0.00** |
| 2 | `range_unit_economics._setter_comm_in_window` / `loaded_cac.read_setter_comp` | SETTER PAYOUT LOG, windowed by **payout date** | **$0.00** |
| 3 | `sheets_pull` → `snapshot.costs.*` → `hormozi_metrics`, `metrics_engine` | sums the same tracker columns again, by its own column numbering (#19/#20) | **$0.00** |
| 4 | `compass_engine.commission_pct_of_cash` | a **rate**: in-window read, else FY26 **6.3%** of cash | **6.3%** (assumption) |
| 5 | `config.CLOSER_COMMISSION_BY_OFFER` | a per-offer table (GP 750 · SE 1500 · …) | validation only |
| 6 | `sales_scoreboard` | per-person tracker cells | $0 per person |
| 7 | `scenario_engine` | scales a per-close commission held constant | derived |

### The rate path contradicts itself

Path 4 uses one rate on **two different cash bases**, so the same engine
reports two different commission costs per client depending on which surface
you open:

| surface | formula | live |
|---|---|---|
| compass roadmap, month 0 | `6.3% × cash **in month**` = $987.09 ÷ 3.15 closes | **$313 per client** |
| simulator cost card | `6.3% × cash **over term**` = $4,177.70 ÷ 4.33 clients | **$965 per client** |

The simulator card's total sits at **$1,455.86 per client above ads** (CAC
$3,812.88 vs spend-only $2,357.02).

### Commissions are hidden in OpEx

`outflow_bands` maps both ledger accounts to a plain `opex` band:

```python
"closer commission": "opex",
"setter commission": "opex",
```

They are real, variable, per-deal acquisition costs and currently arrive in
the cash-flow view merged, unlabelled, with rent and subscriptions.

---

## 3 · HOW QUALIFIED SETS ARE COUNTED FOR THE BOUNTY

Asked directly because the bounty is paid per set, not per close, so the
count drives the cost.

**Today the bounty is one row in the SETTER PAYOUT LOG.** 194 deal rows,
and the set fee is flat on every single one:

- set fees: **194 rows, distinct values = {$50.00}, total $9,700**
- **127 rows are marked `Won = No`** and still carry the $50 — the bounty is
  paid whether or not the deal closes, exactly as ruled
- % bonuses appear on **64** rows, total **$13,812.98**
- setter attribution: **Unattributed 121 · Coby 42 · Maran 30 · Akila 1**

**The log records no qualification flag.** There is no column that says a set
was qualified; "qualified" is the payer's judgement at the moment the row is
added. So the honest statement is: *the bounty count is the number of rows
somebody entered in the payout log*, and the engine must use that, label it,
and not pretend a qualification rule was applied that the evidence does not
show. The 121 unattributed rows mean per-setter bounty totals are
unavailable for most of the history — stated, not estimated.

---

## 4 · THE GST BASIS IS ALREADY EX-GST IN PRACTICE

Every checkable % bonus in the payout log matches 5% of **ex-GST** cash, and
none matches 5% of GST-inclusive cash:

```
bonus == 5% of EX-GST cash: 62      bonus == 5% of INC-GST cash: 0
```

Worked rows, straight from the log:

| deal | cash recorded | bonus | 5% of cash ÷ 1.1 |
|---|---|---|---|
| Lucas Reid | $3,355 | **$152.50** | 5% × $3,050 = $152.50 ✓ |
| Milad Alizadeh | $3,300 | **$150.00** | 5% × $3,000 = $150.00 ✓ |
| The Leopard Deli | $5,000 | **$227.27** | 5% × $4,545.45 = $227.27 ✓ |

R-GST is not a new rule to impose; it is the rule already being followed.
Note the corollary: **the tracker's Cash Collected column is GST-inclusive in
the later era** ($3,355) but was ex-GST earlier ($3,050 for the same $18,300
Growth Pro package in January). Any % applied to that column must convert
first, per era.

---

## 5 · THE RECORDED HISTORY — WHAT IT SHOWS ABOUT PAST REGIMES

46 won deals in the last 12 months; **43 carry a recorded closer commission**,
26 a setter commission. The tracker's last won row is **2026-07-20**.

**Closer rates by era** (recorded values, most common first):

| value | n | reading |
|---|---|---|
| $1,500 | 14 | Scale Engine, current rate |
| $1,400 | 7 | Scale Engine, earlier rate |
| $700 | 7 | Growth Pro, earlier rate (ruled rate today is $750) |
| $900 | 6 | Growth Pro — **the "May-only" override, still being paid in June and July** |
| $625 | 4 | partial/split collections |
| $2,800 / $3,000 | 2 | Scale Engine multi-venue |

**Two findings here that need your eye, not my assumption:**

1. `config.CLOSER_GP_MAY_OVERRIDE_AUD = 900` is documented as a May-2026
   one-month override, with `CLOSER_MAY_OVERRIDE_ACTIVE = False` and the
   comment *"May 2026 is over; GP reverts to $750"*. **The tracker shows
   $900 paid on every Growth Pro close in June and July** (06-04, 06-05,
   06-24, 06-30, 07-17, 07-20). The override never reverted in practice.
2. **Coby's closes are recorded at the full rate, not the junior rate.**
   Every Coby-closed deal in the tracker carries Kalin's number:

   | close | package | closer | recorded |
   |---|---|---|---|
   | 2026-05-13 | Scale Engine | Coby | $1,500 |
   | 2026-06-30 | Growth Pro | Coby | $900 |
   | 2026-07-07 | Scale Engine | Coby | $1,500 |
   | 2026-07-17 | Growth Pro | Coby | $900 |
   | 2026-07-20 | Growth Pro | Coby | $900 |

   The July junior policy ($550 / $1,000) and Kalin's 3% override do not
   appear in the tracker at all. Under the ruled structure these five deals
   would total $3,650 rather than the $5,700 recorded — the fit check will
   report them as mismatches rather than quietly restating them.

**Setter rates by era**: nine deals at a flat **$100** (Oct–Dec 2025), then a
$50 + 5% pattern that fits some 2026 deals exactly ($202.50 on $3,050;
$362.50 on $6,250; $375 on $6,500; $675 on $12,500) and not others ($350 and
$1,295 do not fit any single rule). From **May 2026 the tracker's setter
column is blank on every deal** — the SETTER PAYOUT LOG took over.

---

## 6 · WHAT XERO HAS ACTUALLY PAID

Monthly granularity **is** available from the existing report reads — no new
scope needed.

| month | Closer Commission | Setter Commission |
|---|---|---|
| 2026-04 | $8,350.00 | $2,225.00 |
| 2026-05 | $8,100.00 | $2,868.50 |
| 2026-06 | $7,900.00 | $3,175.90 |
| 2026-07 | $8,485.00 | $4,870.00 |
| 2026-08 | $2,912.55 | $322.16 |
| 2026-09 | $550.00 | $350.00 |
| **total** | **$36,297.55** | **$13,811.56** |

Two things stand out. August and September collapse — consistent with the
tracker stopping on 20 July, so payouts stopped being raised. And
**September's closer commission is exactly $550.00**, which is Coby's junior
Growth Pro rate under the current ruling — the first sign of the new
structure reaching the books.

For scale: Xero paid **$50,109** in commission over six months while every
dashboard surface reported **$0** for the current window.

---

## 7 · WHAT THIS MEANS FOR THE BUILD

- One engine, event-level, rulebook-driven — four computing paths collapse to one.
- A blank cell is not $0. Counted = recorded where present, else accrued from
  the rules, chipped so you can see which.
- Commissions must be accrued from **rules × facts**, because the source of
  record has been silent for two months and will lag again.
- Past deals are costed at the rules in force on their close date; the $900
  Growth Pro era and the full-rate Coby closes are evidence of what those
  rules were, and where they contradict today's ruling that is reported, not
  reconciled away.
- The bounty is per set from the payout log, not per close — so setter cost
  per close moves with the close rate, and the drawer has to say so.
- Commissions leave the unlabelled OpEx band and become a named sales line.
