# STATUS — served-cfo-agent session log

## 2026-09-24 (5) — R-PIOLO-PARITY: FINANCE INHERITS THE OWNER (#167)

Deploy → b25750f8 SUCCESS. Suite **1490**. Triple scan **0 findings**; leak
hunt (now policing ad_domain) clean. Zero writes.

Piolo == owner on the finance dashboard, by INHERITANCE: the allowlist is
gone, require_owner is the finance-grade gate, and a new owner surface is
his the moment it exists (proved on three post-#161 pages). Exceptions live
in one owner-edited list (ships EMPTY); the "Withdraw from Piolo" CSM
toggle is on the CSM page, journaled, no deploy. Exactly three strict
owner-only items: the discreet toggle, credential/env, the exception list.
Drilled live: toggle round-trip · alias confirmed BY piolo, re-ruled BY
rydel, both journaled · EDITH byte-identical on both channels, commissions
answered, voice 200. 27 superseded tests rewritten with reasons.


## 2026-09-24 (4) — IF EVERYONE PAYS vs WHAT ACTUALLY LANDED (#166)

Deploy → 27491325 SUCCESS. Suite **1490**. Zero writes.

The Today net-margin tile is TWO PANELS on one cost basis: **28.5%** if
everyone pays ($79,755 contracted MTD) vs **−32.8%** on what landed
($37,227 collected — 46.7% of the month) · last 30 days (26 Aug → 24 Sep)
**−52.4%** · the gap **$42,527.63** with a door to the unpaid clients ·
AR reconciles with the $20,189 residual NAMED (prior-month AR +
bank-transfer clients outside Stripe) · month-end 27.8% optimistic vs
20.2% realistic (trailing pace 86.5%), each labelled with its assumption ·
"collected" joined the waterfall's basis switch · net_margin joined
freshness TILE_INPUTS (no more "age unknown"); each panel stamps from its
own inputs · EDITH drill answers both margins, both windows, the gap and
the top unpaid, template-filled. 12 new tests incl. the one-cost-basis
proof and the un-mocked trailing-rate maths.


## 2026-09-24 (3) — NET PROFIT, TRUTHFULLY (#165)

Deploys → a57195ed, 1aedcca7 SUCCESS, health ok. Suite **1478**. Zero
writes to Xero/tracker/GHL (the OAuth token exchange is the documented
exception — it touches no books).

**The three witnessed failures, closed with evidence**: the 6.9% was EDITH
dividing two numbers from a ROLLING mid-month Xero block nothing owned
(calendar August: 25.3%) · LTGP:CAC used contribution margin — acquisition
counted twice; now GROSS 63.8% (2.95× → ≈4.4×), everywhere, with the reason
stated · the August three-way (Xero $81,107 · Stripe $61,198 ex-GST ·
contracts $98,641) decomposed with invoice evidence: Stripe sales enter
Xero as payout deposits coded to Sales; ~$20.6k invoiced to bank-transfer
clients, $15,378 unpaid (the AR). "STRIPE IS LATE" was a 2-hour snapshot
stamping a 20-minute promise — the tick probes Stripe itself now.

**Built**: pl_mapping (owner-ruled account → ladder line, journaled,
unmapped never binned) · pl_engine (ladder × management/recognised/cash ×
six named calendar windows, bridge, MTD pro-rata + projection, one-offs
flagged, PIF spread via the Health tab's contract÷term column, 25% tax
accrual labelled) · pl_reconcile nightly (first run: 2 findings) ·
/dashboard/pl waterfall + mapping page · TODAY net-margin tile (nine tiles
now, by #165's name) · answer_guard (every financial number engine-backed
THIS TURN; deflection rewritten; decoy declined) · Stripe stamp decoupled.

**AUGUST BY HAND**: 13 raw lines mapped and summed manually = the engine to
the cent (delivery $33,577.93 · acquisition $11,961.75 · overhead
$15,048.43 · net 25.3%); management $29,991 (30.4%, tax $9,996.92 = exactly
25% of PBT); cash $10,270.62; the bridge names every difference. Sept MTD
28.5% beside a 27.8% projection — after fixing my own MTD flattery (37.8%
from full-month revenue vs part-month costs, caught on the first live
read).

Artefacts: PL_DIAGNOSIS.md · dashboard/evidence/zero-writes-165.json ·
scan evidence · DECISIONS #165.


## 2026-09-24 (2) — ONE CLOSE REGISTER: EVERY SURFACE TELLS THE SAME TRUTH (#164)

Deploys → 72c95bd7, fe599093 SUCCESS (fe599093 serving). Suite **1452/1452** green on the final tree
(the one fpdf test needed fpdf2 installed into the LOCAL venv; it was
always in requirements.txt). Zero writes to the tracker, GHL or Xero;
no token minted; GHL_EMAIL_TOKEN untouched; the timeline repo untouched.

**THE FOUR, ON EVERY SURFACE, IDENTICAL** (evidence:
scripts/close_register_evidence.py run on the box 14:07 AEST):
30d activity — /ads **4** (engine alone said 2) · SALES **4** · travelling
MTD **4** · tiles **4** · _closes_union **4** · EDITH "what have we closed
this month" names all four. Cash **$8,882.50** identical on /ads and SALES
(matched Stripe, R-CASH); contract **$72,900**. 30d cohort — **3**, and the
page SAYS why (Orlando's lead arrived 2024-11-02: id-exact to "Nov Ad
Video v1", closed 22 months later). Tiers: activity 2 from ads (Orlando,
Koji id-exact) · 2 not attributable (Harman, William — leads carry no ad
stamp). Register: **81 entries · 55 confirmed · 26 proposed-needs-evidence**
(proposed are counted SEPARATELY, never inside a headline).

**THE CAUSES OF "1"** (CLOSE_REGISTER_DIAGNOSIS.md, all measured): three
surfaces said 1 for three DIFFERENT reasons — /ads' cohort default on a
tracker-only engine (Harman + William had NO tracker lead row: no window,
no clock, no toggle could ever show them — the all-time grid held 61 deals
without them); SALES' inline tracker filter beside a cash line built from
four; EDITH's third private tracker reader, which also threw away "this
month" and answered all-time. Hypothesis (c) KILLED — the headline never
hid tiers; the POPULATION was the subset. (d) overtaken — Koji was typed
into the tracker on 23 Sep; the "1" Rydel saw WAS Koji.

**WHAT SHIPPED**: close_register.py (detection = #161's four sources
all-time; enrichment with provenance; cash = matched Stripe ONLY, tracker
cell beside; both clocks on every record; confirmed needs authority or two
sources) · every consumer rewired with a single-call-site guard
(tests/test_one_close_population.py) · /dashboard/closes ledger (evidence
chips, attribution WHY per row, Piolo lines, owner-only RECORD A CLOSE:
real evidence picked from a list, verified, journaled; free text refused) ·
scan-2 shared keys closes_count/closes_cash per (window × clock) + register
engine-pair + EDITH drill · daily reconciliation riding the freshness tick
+ ground-truth Scan 3 (drills: scripts/close_register_drills.py — remove a
close → S1 names deal+source; force a divergence → both values named).

**KOJI/POMPOKO ALIAS**: production held alias "sanatani rombola" →
**'Pompoko Ramen'** (the venue) — the "recorded as Koji" premise was stale.
Journaled as a correction/confirmation (register journal + payments
journal, charge ch_3UIj5R…) with Rydel's wording. OPEN NAMING QUESTION for
Rydel: every system calls the venue "Pompoko Ramen"; the brief says
"POMPOKO BAR" — renaming is a tracker/Health-tab edit at source, not the
agent's.

**FOUND LIVE, FIXED IN DEPLOY 2**: a matched charge moved a close's CASH
but not its EVIDENCE — Koji showed $1,650 collected beside "missing: a
matched payment" and a ✗ Stripe chip. Matched charges now join
evidence.charge_ids. Plus R-PIOLO: register entries carry the tracker's
commission cells — /dashboard/api/register now scrubs per-person pay for
non-owner roles (tested).

**WHAT THE GATES CAUGHT IN MY OWN WORK BEFORE DEPLOY**: funnel arithmetic
in the ads blueprint (I13 — moved into close_register.scoreboard_overlay);
a badge that wasn't a door (I14); a route classified by omission
(evidence-options → money-truth, owner-only).

**RECONCILIATION, FIRST RUN**: ok — no source knows a close the register
lacks. 26 aged single-source entries flagged S2 by name (Michael
Pulvirenti 28d, Kristeen Hammond 55d, … krish 128d): each needs evidence
or a human ruling — they sit as proposed, never counted.

**FLAGGED FOR RYDEL, NOT DECIDED**: the POMPOKO BAR / Pompoko Ramen naming
· Harman's and William's tracker CLOSER cells read "Showed" (a column
shifted at source — their closes credit "unassigned" until fixed) · the
26 proposed entries want a sweep (some look like stage-noise, e.g.
GHL-stage-only rows >100 days old) · the closed-deal form is still not in
the mirrored custom fields (#161), so its chip reads ✗ on every close.

**SCANS ON fe599093**: scan 2 — 91 keys, 0 divergences, 10 engine checks (register pairs included); scan 3 clean including the new register-vs-raw-sources check; scan 1 clean once taught that a hidden scan stamp is not a tile. Live access probe PASS: coo reads the ledger and the register API with every pay key scrubbed; declare/rebuild/evidence-options 403; the owner's empty declare 400s with the evidence refusal. Drills (local, in-memory stores): remove-a-close → the reconciliation names the deal and the source; forced divergence → both values named. The accepted-declaration path is unit-proven only — recording a fabricated close on production would violate the law this wave enforces.

## 2026-09-24 (2) — ALIASES APPLIED · CONSULTS COUNTED · THE ESTATE SWEPT (#162)

Deploys → d28a8617 (this wave), then #163/#164 landed on top from a parallel
session; my late close-candidate fix shipped inside their fe599093 after an
isolated-worktree verification (1,425 green). Health ok. Suite green at every
push. Zero writes to the tracker, GHL or Xero.

**THE MATCHER**: candidates were tracker-only — the roster's venues were
never names, which is why "Pottery Green Bakers Gordon" (the client's own
name) drew "nothing close enough to guess". Worse, found while proving it:
the roster index read column 7 (START DATE) as MRR — production held Pottery
at $12,022,025/mo, so amount corroboration had been comparing charges
against dates-as-dollars forever. Header-named columns now; venues are
ranked evidence-tagged candidates; auto stays alias/id/email/phone.

**THE RULINGS**: three payer aliases journaled with charge ids. Panel
7 rows / $19,552.50 → **0 / $0** (2+2+3, both Nirosha casings under one
alias). Walkway $6,100/47d overdue → **$1,067.50/16d** with receipts
itemised; 62Thirty → **$0**; AR $70,248.83 → $62,716.33. Future charges
from all three payers auto-attach. The panel shows cents now — '{:,.0f}'
had rounded the fifty cents away.

**THE CONSULTS**: `appointments.py` reads every calendar directly (6 found;
events carry +10:00 offsets). 12 booked today → 1 Oct with cancelled (3),
test (2) and onboarding (1) beside, follow-ups flagged; the tile says
"Booked consults · now → Oct 1" and read exactly Rydel's **10** at
verification (two of today's had passed). Pulse, SALES and travelling on
the one source — travelling's booked-on month went 0 → **27**. Sync on the
15-min CRM loop + Refresh now + a freshness contract row.

**THE STANDING RULE**: paid-in-60d + zero/expired roster = status-stale
finding with charge ids. First run: Pottery Green AND Texas Charcoal
Chicken ($3,300 while 'Finished') — the second one unprompted.

**THE SWEEP** (`GHL_TRACKER_SWEEP_2026-09-24.md`): counts, named
mismatches and cause classes across contacts, leads, qualified,
appointments, shows, closes, cash, contracts, status. It also caught my
own #161 defect: 23 recurring payments from long-standing clients reading
as brand-new closes once their real close aged past the scan window —
fixed and pinned.

Artefacts: ALIAS_APPOINTMENT_DIAGNOSIS.md · GHL_TRACKER_SWEEP_2026-09-24.md ·
dashboard/evidence/zero-writes-162.json · DECISIONS #162.


## 2026-09-24 — THE COST CARD, MADE TRUE (#163)

Commit c8ee107 (completing the half that rode into d28a861 while two waves
shared the tree). Suite on the exact committed tree (isolated worktree): 1424 passed,
0 failed. Diagnosis: `COST_CARD_DIAGNOSIS.md`. Zero external writes — the
simulator remains a labelled what-if that writes nothing.

**THE ROOT (D1)**: revenue priced by the measured `deal_mix`; commissions
read a DIFFERENT KEY (`package_mix`) nobody ever set → every deal costed as
a Kalin Growth Pro ($902.50 = $750 + 5% × $3,050) while the revenue card
implied $4,533 a client. One mix now drives BOTH cards (invariant tested);
an override raises a visible warning.

**ALSO FIXED**: bounties on QUALIFIED sets (measured input; payout-log
evidence until sample) · pif_share weighted (was a boolean — any non-zero
read as 100% PIF) · Coby's $350 KPI bonus + $1,000 fast-win (amortised
$100/close, labelled) when he is in the mix · capacity cost in CAC on every
surface (card line "+N from month — $x/mo"; simulate == forward month 1 ==
cohort) · tooling = fixed base + per-seat (per-seat needs Rydel's number) ·
ratios named with the margin source (LTV:CAC · LTGP:CAC at FY26 42.9%
labelled · payback) · "show the math" prints the real arithmetic incl. mix
weights · the 6.3% footnote demoted to labelled reference everywhere; the
dead "% of new cash" control replaced by closer-mix + qualified-rate
controls · behaviour gate gained a cost-card pass (Coby shift lowers CAC;
qualified rate moves bounties).

**WITNESSED SCENARIO, corrected** (cost mix pinned to the witnessed 100%
Kalin GP so every delta is named): CAC $2,443.70 → $2,651.84 — the +$208.13
is entirely the +1 setter +1 closer ($3,900/mo) the 409-lead/75-call volume
needs against today's 2-setter/1-closer team. LTGP:CAC 2.71× → 2.50×. On
live measured defaults the commission line will re-price to the measured
deal/closer mix — RYDEL-VERIFY on /scale.

**PARALLEL-WAVE NOTE**: a second session committed and pushed d28a861 at
12:49 carrying my mid-flight files (diagnosis, config, sales_cost, most of
compass_engine) with the OLD sim_core.js — production briefly served that
half-state; c8ee107 completes it. Its 5 WIP test failures
(closes_view/close_register/scoreboard) are theirs and green at their
committed tip.

## 2026-09-23 — R-PIOLO · EVIDENCE-FIRST CLOSES · MONEY UNDER ANOTHER NAME (#161)

Deploys → 15d9527d, 957139c3, 881dce08, 76445b5b SUCCESS. Suite **1388**.
Triple scan **0 findings**. Live role matrix, carve-out leak hunt and six
close-pipeline drills all pass. Zero writes to the tracker, GHL or Xero.

**THE THREE LINKS, WITH THE EVIDENCE.** The CRM stage moved at **06:03**; the
money landed as **"Sanatani Rombola" $1,650** matched to nobody; the recorder
saw the move at **16:41**; and the numbers only moved when a human typed the
tracker row — the first tracker close since **23 July**. Proved before the
fix: `_stripe_hits("Koji", …)` → **`[]`**, and Koji **absent from the gap
ledger entirely**. The one job that reads closes from the CRM is called from
exactly ONE owner-only button.

**KOJI RESOLVED**: alias journaled (actor + charge id + timestamp);
unattached payments **15 → 14** on the same 120-day window ($42,412.50 →
$40,762.50 — exactly his charge); his close now carries **all four sources**
and nothing missing; lead attribution **ID-exact to an ad**
(`B019_A05_Full-Funnel · TH_Kin Hook_Noodle Asia_v1`).

**R-PIOLO live**: 18/18 granted surfaces 200 · every carve-out and every
money-truth POST 403 · owner unchanged · anonymous refused.

**SIX DEFECTS FOUND BY EVIDENCE, FOUR OF THEM MINE**: my date parser dropped
13 tracker close rows (US-first dates read day-first, exception swallowed) ·
a payment date overrode a close date (William Cooney 11 Sep → 1 Sep) · a
matched payment became a second close (client vs person) · scan 2 caught my
new panel publishing the length of its slice (5 vs the engine's 10) · the
snapshot was serving Piolo every per-person pay figure the comp routes refuse
· and the live EDITH drill caught the CSM carve-out leaking through
*remembered context*, because the handler's deliberate silence handed the
question to the model.

**Flagged for Rydel, not decided**: the tracker's $900 closer-commission cell
vs the rulebook's $550 total on a Coby-closed Growth Pro · 7 payments
($19,552.50) still unattached inside 60 days · cohort cash for engine-sourced
closes still reads the tracker's cash cell, not Stripe · a junk alias
("walkway" → a whole sentence) left in place rather than deleted.

## 2026-09-22 (2) — SYSTEM PAGE · FRESHNESS AS A CONTRACT · EDITH ON EVERY OWNER PAGE (#160)

Deploys → 0b1687e7, 21715fe2, 1991a8f0, d6357e02, 6eddb77a, 16af00b9,
2df40867, bb4e0fac SUCCESS. Suite **1351**. Zero writes
to the tracker, GHL or Xero (the #148 law re-proven); no token minted.

**The System page was not slow — it never stopped talking.** Phase 0's three
passes killed my two obvious hypotheses (CLS **0**, long tasks **0 ms**). The
sixteen-minute idle pass found `/api/memory-status` every 60 s forever, a
`/api/voice-status` every 5 min and a **full panel re-render at +600 s**, all
riding along on the dashboard bundle. Rebuilt from stored results only
(**134 ms** to assemble): requests 23 → **6**, API calls on load 10 → **0**,
idle → exactly one `/api/system` a minute, no re-render, CLS still 0, zero
console errors. Telemetry is now grouped — 81 browser errors that are ONE
bug (the #158 null-innerHTML defect, last seen 19.1 h ago) read as a dozen
fires when streamed raw.

**Freshness was a chain problem.** Every source was inside budget, but the
engine blocks the tiles read were **70 min** old (they rebuilt only on a loop
that sleeps two hours first), today's Meta spend could not refresh at all
(**18.4 h** — store-first archive, idempotent backfill), and NEITHER refresh
button touched what the tiles read. `freshness.py` now owns a stated contract
per source, an as-of computed from a value's INPUTS, a five-minute tick that
rebuilds only when inputs move, and a real Refresh now (owner, rate-limited,
journaled, **Xero never force-pulled** — single-use token). Live after:
blocks 1.6 h → *just now* · Meta 18.4 h → *just now* · **zero stale sources**.

**The dock is a new CHANNEL, not a second EDITH** — same brain, same chat
route, same server-side voice proxy, `channel="dashboard"` beside the
Timeline bridge's `"timeline"`. Owner-only, `EDITH_DOCK=off` kill switch,
loads after first paint in its own boundary, silent until tapped.

**What the gates found that I had not:**
1. **EDITH's brain was DOWN in production.** `anthropic 1.7.0` (resolved from
   a floating `>=0.52.0`) dropped `temperature` from messages.create/stream;
   every business answer failed while glossary answers still worked, so
   nothing showed it. `llm_compat.temp()` fixes it and EDITH's pulse is now a
   System-page row — the brain was the one thing nothing watched.
2. A tile named its OLDEST input, not the LATE one (tracker aged 6 h, tile
   calmly cited Xero's 19 h inside a 24 h budget). Ranked by budget breach now.
3. TODAY's tiles carried **no as-of at all** — `as_of()` existed, nothing used
   it. All eight carry one now, amber + named source when an input is late.
4. The freshness tick ran **inside the test process**, bumping the derivation
   epoch mid-suite and failing an unrelated cache test. Guarded + pinned.
5. "What's our cash on hand" returned the **glossary** — the possessive read
   as "what is…". Split: *what IS x* explains, *what's OUR x* answers.

Gate artefacts: `dock-1991a8f03e00/report.json` (8 steps, fails []) ·
`stale-drill.json` (pause a sync → the right tiles go amber and name it) ·
`one-brain.json` (said on `dashboard` conv 28, recalled on `text` conv 29) ·
`phase0-system-*` before/after. 26 registry entries for the new UI, coverage
gate extended, jargon grep zero. DECISIONS #160.


## 2026-09-17 (3) — VISIBILITY FIX (#151): ratios on screen, AR internal-only, three paid closes

Deploys → a4a17bca SUCCESS. Suite **1106**. The shipped-≠-visible class
named and closed: the ratios Rydel asked for now lead the MORNING-BRIEF
first screenful (LTV:CAC 11.94× · LTGP:CAC 5.12×, doors + labelled
fallback margin, owner screenshot on the live deploy) + a Zone-1 panel
(window selector, 3:1 benchmark line, always rendered). Root cause: the
old KPI cells read the standing engine's nulls below the fold; the honest
engine had no tile. R-PAID: Grappino=Harman resolved (tracker row 112
email-exact + RECOGNIZED row 2 contract $18,300 sheet-recorded); aliases
+ expiring paid-current overrides journaled with charge ids; AR diff =
exactly three rows → current ($77,698.83→$70,248.83). Contract evidence
ladder upgraded (RECOGNIZED cell > derived): all three contracts SIGNED
$54,600, contract ROAS 7.52×. R-AR-INTERNAL grep-pinned (never chases).
New drill: "what's my LTV to CAC". DECISIONS #151.


## 2026-09-17 (2) — DATA SCRUTINY: headline forensics, tab map, AR, unit economics (#150)

Same-day follow-on to the currency wave. Deploys → c5394f1e SUCCESS. Suite
**1103+** (+19 new: test_scrutiny + test_finance_tabs). Zero tracker/GHL
writes (the #148 law re-proven by the same guards).

1. **THE LAW**: every headline tile shows its work (drawer: definition ·
   formula · components w/ source+ids · clock · reconciliation delta) and
   no bare ambiguous label survives (test-pinned grep). "$72,887.52" is now
   "Committed MRR (revenue)" with all 38 rows + cross-tab recon in its
   drawer; the "$1.6k net" (the Zone-1 forecast projection tile) is now
   "Forecast net (projection)" reconciled against THREE actual nets —
   prod: cash net MTD (bank) +$2,009.09 · operating net MTD −$5,327.67
   (tax banded BESIDE) · expected month-end +$34,277.82.
2. **Plausible-lie bugs fixed**: financial_position nets ate BLENDED opex
   (tax+personal as operating cost) → banded; the waterfall re-blended tax
   in its own net line → dual net; LTV:CAC un-gated from the margin read;
   two unlabelled "cash collected" tiles qualified; 100%-margin Xero reads
   fall to the labelled FY26 42.9%.
3. **finance_tabs.py (NEW)** — runtime tab enumeration of BOTH workbooks
   (15 tabs; new/unmapped = surfaced; XML-entity fix prod-caught) + THE
   SHEET RENEWAL LEDGER (RECOGNIZED cols E–K + Sheet5): 8 renewals the
   system never saw (Noodle Asia $8,560 08-18→02-18-27 · Bluebells
   month-to-month extension · Cycho's · At Thai · Panini CO · Walkway ·
   Raama · Pottery Green) now re-base the renewal watch + extend committed
   (labelled lane; month-0 exact with ledger disclosure — prod $74,970.85 =
   recognized + At Thai's ledger MRR). Conflicts surfaced (At Thai,
   Monty's). EXTENSION joined the declaration kinds. Cross-tab recon:
   roster $72,887.52/38 vs ACTUAL $107,196.01/45 vs RECOGNIZED
   $92,796.01/39 vs footer $67,337.52 — 9 deltas caused + owned; 2
   zero-MRR actives EXPLAINED by ledger renewals (At Thai, Pottery Green).
4. **receivables.py (NEW)** — expected (grid+ledger) vs received (Stripe,
   alias-aware) → prod: **$77,698.83 outstanding / 28 clients**; aging
   sums; Bar Elvina $2,350/9d · Leopard Deli $2,500/9d · Walkway $6,100/40d
   + the ones nobody named (Panini CO $6,258/71d, Raama $6,200/71d);
   12 unmatched payments → PROPOSED alias cards; Xero BS AR-line anchor
   rides the daily BAS pull (invoice-level = registered dependency).
5. **Unit economics**: fully-loaded CAC (spend+commissions+tooling config,
   $0 fixed sales labour stated) BESIDE spend-only; LTV per package
   (config PACKAGE_TERMS authority); LTV:CAC + LTGP:CAC per cohort/T90 w/
   provenance + 3:1 "benchmark, not target"; union-close fallback for the
   gap-window CAC (prod-caught). ROAS panel: COHORT cash 1.01× headline,
   receipts 3.29× demoted "not attributable", contract 5.04× with
   signed-vs-derived split + ⚑ chips; briefing v3 regenerated.
6. **decision_cards.py (NEW, owner-only)**: 27 cards live (3 PROPOSED
   closes · Harman's venue · 6 alias proposals · footer · 2 zero-MRR
   resolutions · tab conflicts · URGENT renewals (Pizzicotto, Pottery
   Green, Naan Sense, Firefly) · ad-set mapping · first review session ·
   GHL 56 open-closed flag).
7. Sentinel: tabs watch (change detection) + AR watch (anchor drift) ride
   nightly; all drills live on both EDITH lists (three nets · committed ·
   who-hasn't-paid · did-X-resign · roas).

**Files:** finance_tabs.py, receivables.py, tile_drawers.py,
decision_cards.py (new); finance_analysis.py, range_unit_economics.py,
snapshot.py, forward_projection.py, finance_sheets_pull.py,
client_overrides.py, renewal_loop.py, xero_pull.py, bas_engine.py,
ad_sentinel.py, config.py, dashboard/routes.py, dashboard.js,
dashboard.html, DECISIONS.md (#150), dashboard/SCRUTINY_DIAGNOSIS.md.


## 2026-09-17 — FINANCE CURRENCY + GAP RECONCILIATION + MONTHLY ANALYSIS (#148/#149)

Deploys → 74bbe0ff SUCCESS. Suite **1084** (+13 tests/test_gap_reconcile).
Zero writes to the tracker or GHL (grep + token-usage test-pinned).

1. **Currency audit** (dashboard/CURRENCY_AUDIT_2026-09-17.md): the machine
   ran all month, the humans stopped (no logins since 08-13). SEV1s fixed:
   MRR snapshots were boot-only (32/45 days missing, unrecoverable — now
   daily + null-guarded + today healed $72,887.52/38); GHL contacts mirror
   dead since 07-27 (manual-resync-only — now daily); the sentinel had NO
   watchdog (now: mutual loop-watching, registry rows, LOUD self-retiring
   feed items — dead-nightly drill proven: 3 items fire).
2. **Gap detected + journaled** (#149): tracker close/contract/cash columns
   silent from **2026-07-24** (last close row 07-23) while GHL closed-stage
   activity continued — HUMAN gap (mirror healthy); lead INPUT rows never
   stopped. 08-06→08-12 both-series-zero = the known upstream lead-flow
   outage, excluded.
3. **gap_reconcile.py (NEW)** — GHL-primary window ledger: 3 AUTO closes
   (Orlando Rinaldi 09-09/Food Corp · William Cooney 09-11/Phoenix Hotel ·
   Harman Singh 09-11) derived through the sanctioned lane with opp/contact/
   charge ids; 3 PROPOSED (Kristeen Hammond, Michael Pulvirenti, Jay
   Lunsford US) with missing-evidence named; person→venue bridge via the
   payment email; dedupe + conflict-surfacing test-pinned; **11-row Piolo
   backfill package** live as self-retiring queue items + gap sentinel rung.
4. **finance_analysis.py (NEW)** — three ROAS labelled never blended;
   Sept MTD: spend $7,183.13 · 145 leads · 3 closes · CASH 3.3× receipts /
   1.01× cohort · **CONTRACT 5.05× (floor — Harman CV unknown)** · LTV
   9.35× (inputs provenance-labelled) · **payback ≈ 1 month** (cohort cash
   crossed spend on Harman's 09-14 payment). Verdict engine cites its
   deciding figures. Owner briefing v2 (kv-versioned md+PDF, owner-only
   routes); dashboard ROAS panel (Zone 4); EDITH drills on both lists
   (roas · which-three-closed · what-did-I-miss · what's-stale).
5. **Drift sweep** (dashboard/DRIFT_SWEEP_2026-09-17.md): renewal scan
   clean · projection month-0 EXACT (drift 0.0) · sets partition green but
   62% of 7d spend UNMAPPED (graphics/retargeting candidates exist + 2 new
   US sets — Rydel maps) · ZERO R-A2 review sessions since 08-24 · footer
   mismatch + 6 won-not-on-Health + 6 zero-MRR actives + 7 cash-needs-
   logging + 4 unmatched payments → Piolo/Rydel register · 56 GHL closed-
   stage opps still status open (flagged to GHL owner, never re-staged).

**Files:** gap_reconcile.py, finance_analysis.py, scripts/currency_probe.py
(new); app.py, automations.py, action_feed.py, ad_sentinel.py,
mrr_snapshot.py, ghl_mirror.py, dashboard/routes.py, dashboard.js,
dashboard.html, DECISIONS.md (#148/#149), test fixes (footer/BAS/consult
date-rot), tests/test_gap_reconcile.py (new).


## 2026-08-17 — CSM INVESTMENT: model + measure + hold to 4x (#146)

The CSM-hire cockpit ships as the repo's FIRST owner-only domain. Suite
**1086** (from 1023; +63 across 5 new test files).

1. **csm_model.py (NEW)** — pure math core. Reproduces the Sequence-to-
   Success v2 printed figures as regression (16 checks green: per-client,
   book, floor/base/upside, loaded ~3.1x beside the source's unloaded 3.5x);
   two ROI clocks (cohort vs steady-state, never blended, test-pinned);
   4x solve = 68.7% renewal on the loaded cohort clock (between base and
   upside; Y1 4x unattainable in every scenario, stated); layer-vs-hire
   lens; funding_paths() is a pure function of owner-config inputs (no
   director constants anywhere — grep-asserted); comp accrual table with
   90-day clawback.
2. **csm_baselines.py (NEW)** — Gate-0 B1–B5 from data with measured/
   placeholder labels: B1 term-length-aware renewal (survivorship-BOUNDED —
   the first run read 100% because churned clients weren't in the stores;
   now the known-churned list bounds the rate and the label says so);
   in-term completion from cash/contract on ended terms; B2 refund split
   (Xero line total + Stripe per-charge evidence; remainder FLAGGED —
   transaction-level Xero is a registered dependency); B3 expansion
   (step-up proxy from repeat won-deals; product lines don't exist yet —
   placeholders retained, declarations measure forward); B4 dated book
   ledger (kv, join/leave events) + owner tiers + second-CSM trigger +
   workload preview; B5 DQS proxy from the bridge (labelled proxy).
3. **Declarations** — DOWNSELL/CONTINUITY + EXPANSION (8 subtypes +
   first-6-month value) join the ONE #135 flow: preview/apply branches,
   convergence semantics (one-off expansion = cash, converges by
   definition), Piolo edit text (unknown kinds now LOUD, never wrong),
   projection additive stream, roster apply, watch clearing (downsell =
   decided outcome), dialog + Mark-continuity inline button.
4. **csm_plan.py (NEW)** — the domain hub: masked-journal owner config
   (director figures kv-only), Gate-0 checklist (auto data ticks with
   evidence + owner human ticks), nine-risk live register, ladder calendar
   from real terms, NRR (starting cohort, mid-window join excluded —
   test), scoreboard K1–K6, comp accrual vs Xero-paid (activates at
   start), actuals overlay (baseline-rate renewals credit $0 — test),
   scenario publish (M8 overlay — the projection panel note, labelled
   what-if), EDITH drill + owner context injector, sentinel watch
   (owner-only lane, never the shared feed).
5. **Surfaces** — /dashboard/csm (7 tabs, watermark + no-screen-share
   banner, keyboard tabs, ?tab=, explain-this → EDITH narrates from the
   engine); Zone-1 owner card (ships hidden, only an owner 200 reveals —
   fail-closed, structural test); DISCREET MODE (session flag, hides card
   + overlay + shows header chip). EDITH registered on BOTH handler lists;
   CSM turns never persist to memory/distillation (either side, any
   channel — tested end-to-end through /api/chat).
6. **csm_docs.py (NEW)** — D4 CSM_ANALYSIS briefing (kv-versioned md +
   PDF, regenerable from chat or page; no director figures by design) +
   D5 candidate comp page (stripped; preflight forbidden-token proof;
   generator REFUSES on a dirty preflight — test). D6 specs in docs/:
   GHL ingestion (+ Tristan-ready task text, not created), health score,
   CSM role scope, Timeline panel outline.
7. **Sentinel** — nightly csm_watch (baseline freshness, ledger, shared-
   memory leak probe) in the owner lane + SENTINEL_QUEUE.md; weekly
   security replay now probes 8 anonymous CSM routes (any 200 = LOUD P1).
8. **SG_RATE = 0.12** — the single super-rate authority lands beside
   SUPER_BASELINE_MONTHLY (which is NOT SG-derived; never multiplied).

**Files:** csm_model.py, csm_baselines.py, csm_plan.py, csm_docs.py (new),
client_overrides.py, renewal_loop.py, forward_projection.py,
finance_sheets_pull.py, mrr_snapshot.py, xero_wages_categoriser.py,
ad_sentinel.py, dashboard/routes.py, dashboard/templates/csm.html (new),
dashboard/templates/dashboard.html, dashboard/static/js/dashboard.js,
DECISIONS.md (#146), dashboard/CSM_DIAGNOSIS.md (new), docs/CSM_*.md (new).
**Tests:** 1086 passed (63 new: test_csm_model / test_csm_declarations /
test_csm_plan / test_csm_confidentiality + existing suites green).


## 2026-08-08 — Roster engine + payment-class ruling (#131) + row control

1. **roster_engine.py (NEW)** — the ONE cellspec→roster path. attribution_engine
   records members at every counter increment (I17: len(roster) == cell, both
   clocks, every metric incl. anomaly classes). Consumers refactored to it:
   /ads/api/roster (all tabs + tier rows + zero cells + anomaly metrics), the
   dossier lead ledger, the JS anomaly panel — parallel person-list code deleted.
   Rosters carry identity chips (id-linked / name-match / ambiguous / tracker-only),
   name-discrepancy, event-with-provenance, funnel chips, GHL + tracker links;
   ?roster= deep links; panel sorts (event/state/cash). I17 in the compute
   invariant sweep + suite + nightly 20-cell sampling (drift = ACTION-lane loud).
2. **DECISIONS #131** — dateless-close payment-class auto-derivation: Stripe
   first-payment matched by EMAIL auto-derives blank Close Dates (journaled
   "ruling-conversion DECISIONS #131" w/ charge id; one feed notice, 7d retention;
   idempotent; nightly rung in resolve_dates). GHL stage stays PROPOSED forever;
   GHL payments + Xero rungs NOT built (both 401 at probe — zero speculative code).
   P1 cards stop generating for derived closes.
3. **Row control** — 70/150/300/All on grid + tracker tables; full-dataset
   sort/find before the slice; tier rows pinned; localStorage + ?rows= state.
   D4 finding: no hard cap existed — ~70 was the natural 30d rollup shape.

**Files:** attribution_engine.py, attribution_verdicts.py (ladder_groups extraction),
roster_engine.py (new), resolution.py, ads_truth.py, dashboard/ads.py, adsapp.js,
ads.html, adsapp.css, DECISIONS.md, dashboard/ROSTER_DIAGNOSIS.md (new).
**Tests:** 683 passed (21 new in tests/test_roster_engine.py).

## 2026-08-07 — PD engine fixes (Master Spec v1.1 reconciliation)

**What changed (4 surgical items; send path untouched):**
1. `segments.py`: new **PD_ACTIVE** state — `pd-active` contacts suppressed from all
   marketing except campaigns registered in `PD_MACHINE_CAMPAIGNS`; precedence over
   S2 (S0/S1 still win). Post-cycle **PD_QUIET** (14-day total silence, blocks even
   pd-machine sends) then S4-WARM with a recent-completion WARM cap. Named
   approximation: month-granular `pd-completed-YYYY-MM` → quiet through day 21 of
   the following month; conductor ledger replaces this later.
2. `segments.py`: discount lock now catches **voucher** (word-boundary, both numbers).
3. `DECISIONS.md`: #129 (conductor autonomy amendment to #110 — two-gate sanctioned
   execution) + #130 (ladder amendment to #112 — PD_ACTIVE/PD_QUIET as implemented).
4. Preflight inventory note (below). The conductor itself is NOT built.

**Preflight "not in any other active Served sequence" — inventory sources (for the
conductor build):** (a) GHL per-contact active-workflow list via API, (b) the
conductor's own enrolment ledger, (c) fallback: any `seq-*` / `*-active` tag.

**Files touched:** segments.py, tests/test_email_gate_hypothetical.py, DECISIONS.md,
STATUS.md (new — this file).
**Tests:** suite BEFORE: 671 passed. Target file: 17 passed (5 new PD tests + voucher).
Suite AFTER: 676 passed (671 baseline + 5 new), 0 failures.

---

## 2026-09-18 — DASHBOARD HARDENING (#152): server-rendered truth · crash isolation · real-browser gate

**Phase 0 named the failure** (dashboard/CRASH_DIAGNOSIS.md): 16,225px scroll
wall, every headline client-filled by a 40-call unguarded orchestrator;
/api/action-feed had been 500ing on EVERY prod load for days (int severity →
jsonify sort_keys crash) with the panel silently skeleton'd; edith armed a
getUserMedia mic loop on every load; Phase-0 artefacts in
dashboard/evidence/phase0/.

**What shipped:**
- dashboard/exec_top.py — server-rendered EXECUTIVE TOP: 8 tiles + verdict +
  summary cards baked into the landing HTML (kv-cached engine blocks, refresh
  rides the 2h loop + boot warm; request path read-only; freshness stamp per
  tile; undefined = labelled state). Landing = tiles + verdict + cards, ≤ 8
  tiles, nothing below the cards. Cache-Control: no-store.
- IA split: /dashboard/view/<area> pages (brief · cash · sales · unit-econ ·
  projection · renewals · outflows · team · receivables · decisions
  [owner-only] · system) from partials/area_*.html; card count == page count
  (test-pinned); CSM card server-gated owner+discreet (#146 honored).
- dashboard.js: boundary() orchestrator — per-panel try/catch, absent
  sections skip, failures render "Panel unavailable — {reason} · retry" +
  telemetry; applyZones skipped on area pages; old LTV/LTGP KPI cells
  REMOVED (one rendering path).
- Voice OPT-IN: edith-wake/edith-clap default OFF (no mic loop on load).
- Telemetry: partials/telemetry.html (FIRST script) → POST /api/client-error
  (auth-gated, rate-limited) → kv ring + hourly buckets; render_health.py
  watches (self-check S1 · error-rate spike · tile freshness) →
  feed:extra:render_health.
- scripts/render_gate.py — THE deploy gate (Playwright, owner session, prod
  URL): 8-tile assertion, labelled-state law, card links 200, area render
  smoke, zero console errors, mobile no-overflow, JS-DISABLED server-render
  proof, post-rebuild hold. Artefacts → dashboard/evidence/gate-<commit>/.
  Drilled: broken build BLOCKED (exit 1) · forced client error reached
  telemetry · injected throwing panel isolated (siblings rendered, zero
  uncaught).
- action_feed._norm_severity + gap_reconcile severity "S2" — the prod 500
  fixed at both ends.

---

## 2026-09-20 — THE SCALING COMPASS (#153): /scale tab · sales pulse · expiring terms

- compass_engine.py: measured defaults (CPL $88.5 n=345 · set 14.8% · show
  90.2% · close 28.3% n=46 · lag [0.73,0.27,0] n=22 · renewal B1 midpoint
  61% [22.7–100] · commissions FY26 6.3% (28.8% in-window read surfaced as
  distorted) · OpEx ex-tax ex-acquisition $45.3k/mo · ε default 0.2 with
  the confounded 1.19 fit surfaced) + the monthly equation forward run +
  bisection target solver + Monte Carlo bands + 3-month backtest +
  scenario/plan-of-record store. Scenario lane only — never actuals.
- /dashboard/scale (owner-only): server-rendered Base hero; inputs with
  provenance chips + reset-to-measured; roadmap table to Dec 2027 with the
  BINDING CONSTRAINT named per month; money view (cohort vs period CAC);
  team view + hire cards; scenarios compare/commit; calibration table;
  briefing PDF.
- Landing: SALES PULSE strip (show rate · close rate · booked calls 7d
  from GHL appointment cache, read-only) under the 8 exec tiles.
- Projection page: EXPIRING TERMS panel (30/60/90; scenario-pin toggles →
  preview API, journal NOTHING; Declare… adjacent) + BURN box (ex-tax,
  tax beside, runway).
- Watches → feed:extra:compass: monthly backtest drift · Plan-2027
  variance · capacity threshold inside hire lead time.
- Gate: pulse-strip assertion + /scale first-paint pass + projection area
  smoke. Suite: [filled at deploy]. DECISIONS #153.

---

## 2026-09-21 — EXPLAIN · SIMULATE · SIMPLIFY (#154)

- dashboard/definitions.json (142 plain-English entries) + definitions.py
  (coverage inventory from code, jargon grep, EDITH explain drill) +
  defs.js (hover 300ms / keyboard focus / long-press tap sheet / "?" mode
  / first-run tours) + /dashboard/definitions legend (auto-generated) —
  100% coverage is a build gate + a render_health watch.
- compass_engine.simulate_month (the simulator's server truth; identity ==
  forward month-1), confidence_word, accuracy_sentence (plain words).
- /scale reshaped: SIMPLE (server-rendered triad + question-headed chain +
  show-the-math + I-want + presets) / ADVANCED (collapsed) / PLAN
  (collapsed). Gate now asserts math parity (page == server), tooltip
  render (5/5 landing sample + scale), collapsed defaults, accuracy line.
- Suite: [at deploy]. DECISIONS #154.

---

## 2026-09-21 (2) — SIMULATOR FIXED FOR GOOD (#155)

- Phase-0 reproduced Rydel's failure exactly: failure (b) lock semantics
  (CPL locked by default; typed CPL ignored + silently reverted; zero
  console errors). scale/SIMULATOR_DIAGNOSIS.md + step artefacts.
- Locks retired: spend+CPL always inputs (number+slider), leads always the
  output; Target mode = spend is the answer; elasticity = CPL visibly
  read-only-derived. sim_core.js = ONE formula file (browser + node);
  200-set parity vs engine = zero mismatches; engine wins on settle.
- scripts/behaviour_gate.py (interaction deploy gate, 3 passes, artefacts,
  posts the LOGIC VERIFIED badge). North-star block (actual·plan·required
  + levers + constraint + what-ifs + pinned inputs), calibration log
  (monthly predictions scored in public), drift alerts. Registry 153
  entries, coverage 100%. Suite: [at deploy]. DECISIONS #155.

---

## 2026-09-21 (3) — HOW WE'RE TRAVELLING (#156)

- scale/TRAVELLING_DIAGNOSIS.md first: what each stage can be evidenced to.
  Key verdicts — consults booked come from the calendar (the tracker's
  set-date column is 0 of 446 rows); PITCHED is an evidenced lower bound
  from the CRM's current stage (no history exists), scoped to this
  window's consults, plus a Piolo package line proposing the column;
  setter activity is cache-only call records (no direction recorded).
- travelling.py: 10 stages with rosters (I17), three-way lead split with
  UNKNOWN as its own bucket, plan-to-date markers on flow stages only,
  pipeline-aware month-end projections, status words with bands and
  confidence intervals (small samples read "too early to tell"), the gap
  finder in clients and cash, cross-checks across calendar/tracker/Stripe,
  EDITH's read with template-filled numbers, saved checks + Monday auto-save.
- /dashboard/scale/travelling — server-rendered from URL state, the
  dual-track funnel as the hero, rosters on demand, "Re-model from
  actuals" and "Save this check". CONSOLIDATION: the north-star levers
  table left /scale; one plan-vs-actual surface.
- FOUND AND FIXED AT SOURCE: revenue_bands didn't know the tracker's
  current picklist spellings ("$50k - $100k"), so those leads parsed as
  UNKNOWN and the qualified rule read them as below-floor — the qualified
  metric was wrong everywhere it is used. Literal spellings added.
- Behaviour gate extended with the travelling contract. DECISIONS #156.

---

## 2026-09-21 (4) — ESTATE TRIPLE SCAN + TRAVELLING DEFECTS + LEDGER (#157)

- A: six travelling defects fixed — confirmed-basis show rate with its
  range and a two-basis gap finder (says when the conclusion flips);
  outcome vs rate as separate statuses; cost/gain polarity; three-way
  status bands; "usually" vs "planned"; identities + named denominators.
- B: ONE qualification rule (attribution_engine.qualify_lead) — there were
  two. Picklist changed at source 2026-08-26; 75 leads had been parsing
  UNKNOWN and reading as below-floor. September qualified restated
  24% → 51%; journalled at restatements:qualified_picklist_2026_09.
  A new spelling now raises a loud drift finding.
- C/D: scripts/triple_scan.py (works / agrees with itself / agrees with
  reality) + ground_truth.py + HEALTH rows + watchdog. First run: 11
  findings, all scan defects, fixed. Second run: 0 findings across 19
  pages, 13 metric keys, 6 real external checks. ESTATE_SCAN_2026-09-21.md.
- E: PROMPT_LEDGER.md — 37 briefs by verified presence. 30 shipped,
  3 partial, 1 not run (DASHBOARD-UX-OVERHAUL), 1 superseded, 1 stale doc.
- F: stage_history.py — the recorder remembers what the CRM forgets, in
  this repo's store, on the existing poll. Pitched is measured from today.

## 2026-09-24 (5) — EDITH ANSWERS THE QUESTION (#168)

- The witnessed thread closed: the three-basis wall and the guard's
  refusal copy are retired; the replay is a shipped test.
- MONTH TO DATE = the 1st through today for revenue AND costs on every
  basis and panel; day counts in the window words everywhere ("24 of 30
  days"); the retainer and normalisations pro-rate inside MTD; both
  net-margin panels carry identical window words and one cost figure.
- answer_engine.py: resolver (question → metric/basis/window/shape,
  logged + shown as "Answered as: …"), answer-shaped outputs
  (total_costs, per-day pacing, deltas), POST /api/calc.
- Validator v2: a blocked number still answers the question from the
  engine; blocks logged with what was answered instead.
- Suite 1,492 green; registry +5 entries (jargon clean).
