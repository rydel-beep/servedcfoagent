# Hiring Model V4 — Cash-on-Hand + Runway + Raises + Graded Sustainability + Team Re-categorisation

## What changed

### 1. Cash-on-Hand Override
Xero bank balances are unreliable due to reconciliation timing (CommBank showed -$57k).
Added config overrides sourced from Rydel's confirmed position:
- **Bank balance:** $140,007.29
- **Stripe incoming:** $18,000
- **Deployable buffer:** $40,000 (of $61k total buffer)
- **Tax/BAS reserved:** $20,000

Config: `CASH_ON_HAND_OVERRIDE`, `CASH_STRIPE_INCOMING`, `CASH_DEPLOYABLE_BUFFER`, `CASH_TAX_RESERVED` in `config.py`.

### 2. Forward Cash Projection
Each forward month now shows a running cash balance (starting bank → cumulative net flows).
The hiring model reports `cash_runway_month` — the first month cash goes negative.

### 3. Graded Sustainability (bug fix)
**Before:** Binary `can_sustain: fwd_net > 0` showed a green checkmark even at 402% team ratio.
**After:** Three grades with distinct thresholds:
- **Healthy** (green): team ratio <50%, cash positive, net positive
- **Tight** (amber): team ratio 50-80%, or slight net negative
- **Unsustainable** (red): team ratio >80%, cash negative, or net loss >$5k/mo

### 4. Raise Modeling
New raise form allows modeling salary increases for existing team members alongside new hires.
Raise cost stacks with hire cost in the forward projection. SPOF flag carried through.

### 5. Team Re-categorisation
Fixed 5 people wrongly bucketed under "leadership" due to C-LEVEL department tag.
Person-level overrides in `team_model.py`:
- Tristan Borebor → delivery_tech
- Ryan Piolo Dulay → admin
- Miguel, KC → leadership (confirmed)

## Files changed
- `config.py` — cash override config
- `snapshot.py` — cash_position section
- `hiring_model.py` — graded sustainability, cash projection, raises
- `team_model.py` — person-level function overrides
- `dashboard/routes.py` — passes cash_position and raises
- `dashboard/static/js/dashboard.js` — cash KPI, graded table, raise UI
- `dashboard/templates/dashboard.html` — raise form
- `dashboard/chat.py` — cash position in Jarvis context
- `tests/test_hiring_v4.py` — 16 new tests

## Tests
78 total tests pass, including 16 new V4 tests covering:
- 402% team ratio → unsustainable (not healthy)
- Cash projection goes negative when it should
- Raise modeling computes correctly
- JSON safety for Infinity/NaN
