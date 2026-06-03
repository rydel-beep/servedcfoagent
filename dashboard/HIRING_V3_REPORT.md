# Hiring V3 Report — Forward MRR + Contribution Margin + Throughput Lens

## The Problem with V2

V2 judged hires against trailing recognized net ($16,919/mo). But trailing revenue reflects
deals sold months ago. New signings (Amano, Chaan, Casa, Masala, Dcthai, Danka, Rung, etc.)
have collected cash but haven't fully ramped into recognized revenue. Trailing net is the
rearview mirror — the wrong lens for a forward, recurring commitment.

## The Bigger Problem: The Churn Cliff

Inspecting the RECOGNIZED tab (Finance Sheet gid 1407663952) revealed the real issue:

- **0% historical renewal rate** — all 12 finished clients churned, none re-signed
- **Current recognized MRR: $65,420/mo** (29 active clients, excl. The Advocate = churned)
- **July cliff: -$13,233/mo** (5 contracts expire: Panini, Monty's, Walkway, Bluebells, Kisseafoods)
- **By October: $13,618/mo** (only 6 clients remain)
- **MTM floor: $5,037/mo** (Cream House, Masala, AllSpice, Abou George)

```
Month           Rec. MRR     Clients   Delta
June 2026       $65,420      29        (current)
July 2026       $52,186      24        -$13,234 (-20%)
August 2026     $45,520      21        -$6,666
September 2026  $33,872      16        -$11,648
October 2026    $13,618       6        -$20,254
November 2026    $7,533       3        -$6,085
December 2026        $0       0        (MTM not in sheet columns)
```

Even WITHOUT a new hire, recognized net goes negative by August ($45.5k revenue - $50k costs).
The hire isn't the problem — the churn curve is.

## What Was Built

### 1. `forward_mrr.py` — Forward Recognized MRR Model

Pulls per-client, per-month recognition schedule from the RECOGNIZED tab. Computes:
- Forward recognized MRR by month (churn-adjusted)
- Contract expiry schedule with dates and amounts at risk
- MTM floor (recurring clients with no expiry)
- Historical renewal rate (0/12 = 0%)
- Average monthly value per client ($2,242)
- Excludes known-churned clients (The Advocate, etc.)

### 2. Hiring Model — Forward Sustainability Lens

`hiring_model.py` now accepts `forward_mrr` and computes a dual-lens analysis:

**Lens 1 — Cost sustainability (existing, against trailing net):**
Same as V2 — can we afford the cost against current trailing net?

**Lens 2 — Forward sustainability (NEW, against churn-adjusted MRR):**
- Forward recognized net per month WITH and WITHOUT the hire
- Team cost as % of forward MRR (per month)
- When the hire becomes unsustainable due to churn
- Clients needed to fund the hire (contribution margin basis)
- Plain-English verdict

**Sample verdict (Video Editor @ $3,000/mo):**
> "Sustainable now, but churn makes it tight by July 2026. Sustained for 1/6 forward
> months. Requires ~2.1 client contributions to fund. Binding constraint: Lead flow."

### 3. Dashboard — Forward MRR Bar Chart

The Team & Hiring panel now shows a 6-month forward MRR bar chart:
- Bars colored green (above team cost) or red (below)
- Per-month MRR, client count
- MTM floor + renewal rate note
- Next contract expiration warning

### 4. Hiring Result — Forward Forecast Table

When analyzing a hire, the result now includes:
- Forward forecast table: month, recognized MRR, clients, net (no hire), net (w/ hire),
  team cost %, sustainability check
- Churn warning with the specific month it becomes unsustainable
- Contribution margin: clients needed to fund the hire
- Average monthly churn rate from expiry schedule

### 5. Jarvis Integration

Chat context now includes:
- `forward_mrr` summary (months, expiry schedule, renewal rate)
- System prompt explains forward MRR and 0% renewal rate
- Jarvis judges hiring against forward curve, not trailing

## The Honest Insight

The data tells a clear story:

1. **Cash basis ($35.7k net)** — strong right now. New signings collected upfront cash.
2. **Trailing recognized ($16.9k net)** — positive but reflects old revenue mix.
3. **Forward recognized** — drops to breakeven by July, negative by August, without
   ANY new hire. The churn cliff is the constraint, not hire affordability.

**Implication for hiring:** A hire isn't "affordable" or "not affordable" in isolation.
The question is whether the SALES MACHINE can replace churning clients fast enough to
sustain the cost base. At current velocity (~6 closes/30d), Served needs to keep closing
to maintain MRR. Every hire must be evaluated against whether it helps the close rate or
covers delivery for the clients being signed.

## Privacy Verification

- Sales summary: no forward_mrr, no financial data
- Per-client revenue data stays in owner-only context
- Jarvis gets summary only (no per-client detail in chat context)
