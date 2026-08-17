# Pitched & Drifted — Full Automation Master Spec (v1.2 — EVERGREEN)

**v1.2 (RULED 7 Aug — "go evergreen"):** the cohort model is retired. One standing
8-email sequence, relative per-lead timing (D0/+2/+7/+9/+14/+16/+21 offer/+24 bump/+28 end),
48h grace-window auto-enrolment replacing the Launch ceremony, per-lead
`pd_offer_deadline` = entry+28d, ONE standing offer (Venue Growth Blueprint),
copy approved once + refreshed QUARTERLY. Monthly copy cycle: deleted. Cohort
launch machinery: deleted. pd-conductor: deferred (GHL native handles enrolment/dates);
revisit only at volume. Dashboard PD section: deferred until segment earns it.
Layer 3's monthly cycle below is SUPERSEDED by: weekly = read grace alerts + reply alerts;
quarterly = proof refresh + 3-number check (replies, bookings, unsubs). Completion adds
a contact note "PD completed {date}, no response". Cohort-dated build sheet superseded
by pd-ghl-build-sheet v2 EVERGREEN. Everything else in this spec (exits, suppression,
re-entry guard, compliance, seed test, kill switch, no-LLM path, rulings) stands.

*(v1.1 text below retained for reference; where dated-cohort mechanics conflict with
the evergreen ruling, v1.2 wins.)*

**Status: RECONCILED — Edith's 4 findings folded in, 6 open decisions RULED (7 Aug).
Approved for infrastructure build in DRAFT/UNPUBLISHED state only. NO sends, NO publish.**

**v1.1 changes:** S2-DRIFTED renamed → **PD-ACTIVE** (own ladder state; S2=IN_PIPELINE per
DECISIONS #112 would have suppressed PD sends themselves) · DECISIONS #110 amendment written
(conductor's post-Launch autonomy = sanctioned two-gate model, not a boundary violation) ·
"voucher" added to the discount lock · preflight "other active sequence" source defined
(GHL per-contact active-workflow list + conductor enrolment ledger; tag fallback) ·
cohort schedule reconciled (all 8 Notion rows on v3 + shifted dates, live 7 Aug).

This is the complete structure: every component, every workflow step, every rule, every
safety net. Approve this, and everything downstream is just execution.

---

## LAYER 0 — Operating principles (the laws of the system)

1. **The Approved status flip is the only trigger.** Copy existing means nothing.
   Sends happen because Rydel flipped Approved AND clicked Launch. Two gates, always.
2. **The GHL workflow is frozen infrastructure.** Built once from this spec,
   triple-confirmed, never rebuilt. Monthly variables are only: copy + cohort of people.
3. **Notion is the source of truth. Dashboard is the mirror + control surface.**
   Copy lives in the PD Email Review DB; the dashboard reads it and writes back
   only status changes and launch commands.
4. **Every number in every email traces to a Wins DB row.** No exceptions.
   Every proof email carries one real screenshot before Approve.
5. **Approval is invalidated by edits.** If copy in Notion changes after Approve,
   status auto-reverts to "Rydel Review". No silently-edited email ever sends.
   (Implemented as a content hash stored at approval time.)
6. **Humans exit instantly.** Any lead who engages (reply, booking, re-pitch)
   leaves the machine immediately and lands with a human closer.

---

## LAYER 1 — Components (what exists vs what gets built)

| # | Component | Status | Role |
|---|-----------|--------|------|
| 1 | `served-winback` skill | ✅ Exists | Generates monthly set: 8 emails + offer SMS + bump, proof pulled live from Wins DBs |
| 2 | Notion PD Email Review DB | ✅ Exists | Draft → Rydel Review → Approved → Loaded → Sent. Copy of record. |
| 3 | Notion PD Monthly Offers DB | ✅ Exists | One offer per cohort month |
| 4 | Timeline dashboard — PD section | 🔨 Build | Review/approve UI, cohort lead list + AI deal summaries, preflight results, Launch button, live stats, kill switch |
| 5 | `pd-conductor` (Railway service) | 🔨 Build | The bridge: Notion ↔ GHL ↔ dashboard. Preflight, copy loading, enrolment, stats polling, alerts. **No LLM in the send path.** |
| 6 | GHL PD workflow template | 🔨 Build once (GUI, from Layer 2 below) | The frozen automation. AU pipeline `JJQLCr1fl7OHyrpRwSJp`, USA mirror `ieMQNO2paLTKp2HRLETP` |
| 7 | Alert channels | ✅ Exists | Existing Lark + Telegram sales-bot channels carry PD alerts |
| 8 | GHL custom fields + tags | ✅ Spec'd (v1.1) | `pd_stall_reason`, `pd_pitched_package`, `pd_closer` (mandatory dropdown), `pd_pitch_date`, `pd_offer_deadline`, `pd_cohort`; tags `pd-active`, `pd-YYYY-MM` |

**API reality check baked into this design:** GHL's API cannot create/edit workflows —
only add/remove contacts and update fields. Hence: template built once by hand,
conductor drives copy + enrolment via API. If we ever outgrow GHL workflow logic,
the conductor graduates to owning the schedule itself (sends still via GHL = deliverability preserved).

---

## LAYER 2 — The GHL workflow template (THE MINDMAP — this is what you're approving)

### ENTRY
```
Lead dragged into "Pitched and Drifted" stage
  → GHL requires: pd_closer (dropdown, mandatory), pd_stall_reason,
    pd_pitched_package, pd_pitch_date
  → Auto-apply: tag pd-active, tag pd-{cohort YYYY-MM}, status PD-ACTIVE
  → PD-ACTIVE = suppressed from ALL other Served email (newsletter, promos, everything)
  → Lead is now VISIBLE on dashboard cohort list but NOT enrolled.
    Enrolment only happens via conductor after Rydel clicks Launch.
```

### SEQUENCE (after Launch — all times recipient-local, from contact timezone field)
```
E1  Re-Open          Tue 10:00 local   (cohort day 1)
E2  Fit              Thu 10:00 local   (+2d)
E3  Price/ROI        Tue 10:00 local   (+7d)
E4  Timing           Thu 10:00 local   (+9d)
E5  Client Voice     Tue 10:00 local   (+14d)
E6  DIY Truth        Thu 10:00 local   (+16d)
E7  OFFER            Tue 10:00 local   (+21d)
     └─ same day, 13:00 local: OFFER SMS (personalised, ≤300 chars)
BUMP                 Fri 10:00 local   (+24d)
     └─ optional bump-day SMS: per-cohort approval only, default OFF
DEADLINE             +28d (offer expires; deadline token in E7/Bump)
```

**Closer branch (every email that references the call):**
```
pd_closer set     → "you spoke with {{pd_closer}}"
pd_closer empty   → "you spoke with our team"   ← never a guessed name
```

**Hard caps:** 8 emails + 1 SMS (2 with explicit approval) per lead per cycle. Ever.

### EXIT PATHS (first-class — any of these fires at ANY point in the sequence)
```
1. REPLY (email or SMS)     → exit workflow instantly
                            → alert closer via Lark/Telegram with lead + reply text
                            → tag pd-replied, stage stays until closer moves it
2. CALL BOOKED              → exit instantly → alert closer → move to booked stage
3. OPPORTUNITY RE-OPENED/WON → exit instantly (sales took over)
4. EMAIL UNSUBSCRIBE        → exit + global email suppression honoured
5. SMS "STOP"               → SMS opt-out flag set, email sequence continues
6. HARD BOUNCE              → exit + tag pd-bad-email + surface on dashboard fix list
7. KILL SWITCH (cohort)     → all cohort members paused mid-flight (Layer 7)
```

### POST-CYCLE
```
Sequence complete, no conversion
  → remove pd-active
  → 14 days TOTAL email silence (nothing, from anyone)
  → status S4-WARM → standard newsletter cadence resumes
  → tag pd-completed-{YYYY-MM}
```

### RE-ENTRY POLICY  ← new (missing piece #7)
```
A lead may enter PD max ONCE per 6 months.
Dragged into the stage with a pd-completed tag < 6 months old
  → workflow does NOT arm → alert to sales: "manual follow-up only, PD used {date}"
Prevents: same lead getting the "no pitch, just receipts" opener twice
and instantly reading as automation.
```

---

## LAYER 3 — The monthly cycle (what actually repeats)

```
Day −7   /winback runs → full set (8 emails, subjects, previews, SMS, offer)
         → written to Notion PD Review DB, status "Rydel Review"
         → proof-image slots marked; Rydel drops real screenshots
Day −5   Rydel reviews ON DASHBOARD → approves each entry (status flip via dashboard
         → Notion). Edits allowed; any post-approval edit reverts status (Layer 0.5).
Day −3   Conductor runs PREFLIGHT on everyone currently in the PD stage (Layer 4)
         → dashboard shows: cohort list, per-lead AI deal summary, fix list
Day −1   Rydel reviews the PEOPLE: list + summaries + preflight results
         → removes anyone who shouldn't be in (one click per lead)
Day 0    Rydel clicks LAUNCH
         → conductor loads approved copy into GHL (email/SMS assets + custom values)
         → conductor enrols cleared contacts into the workflow
         → confirmation alert to Lark/Telegram: "Cohort {month}: N enrolled, M excluded"
         → Notion statuses flip to Loaded → Sent as sends fire
Weekly   Stats poll → dashboard (Layer 6)
Day +30  Retro auto-generated → feeds the NEXT /winback run
```

**Per-lead AI deal summary (dashboard, Stage 4 of your flow):**
Claude reads GHL notes + opportunity history per lead → two lines:
*stall reason · package pitched · closer · last meaningful touch · anything unusual.*
Read-only intelligence for your Day −1 review. `pd_stall_reason` additionally
selects which angle the E7 SMS leads with (price-stall → ROI line;
timing-stall → deadline line; trust-stall → Ashley line).

---

## LAYER 4 — Preflight (missing piece #3: per-contact validation, no exceptions)

Run per contact before Launch is clickable. Failures → dashboard fix list, lead
held out of enrolment until fixed or Rydel overrides.

```
□ Valid, non-bounced email address
□ venue_name present (no "Hi , about your venue ")
□ pd_closer set → else fallback branch confirmed armed
□ Mobile number present → else lead auto-set to EMAIL-ONLY branch (no SMS step)
□ SMS consent basis exists (prior SMS thread OR mobile knowingly provided) → else email-only
□ Contact timezone set → else default AEST + flag on fix list
□ Not S3 / global-suppressed / unsubscribed
□ Not currently in ANY other active Served sequence
  (source: GHL per-contact active-workflow list via API + conductor enrolment ledger;
   fallback: any seq-* / *-active tag present)
□ Re-entry rule clear (no pd-completed < 6 months)
□ All merge tokens in approved copy resolve for this contact (dry render)
```

---

## LAYER 5 — Compliance (missing piece #2)

**Email (Spam Act 2003, AU):** working unsubscribe in every send (GHL native, verify
in template) · accurate sender identity (Served Marketing / The 97 Group Pty Ltd) ·
suppression honoured across ALL Served sending, not just PD.
**SMS (Spam Act, AU):** every SMS ends "Reply STOP to opt out" · opt-outs actioned
immediately + logged · send window 09:00–19:00 recipient-local, weekdays only ·
consent basis required (Layer 4) — no cold SMS to scraped mobiles, ever.
**USA mirror cohorts:** CAN-SPAM (postal address in footer, prompt opt-out) and
TCPA (SMS consent bar is HIGHER in the US — default: **email-only for US cohorts**
until we explicitly stand up compliant SMS consent capture).

---

## LAYER 6 — Feedback loop (missing piece #5: how it compounds)

```
Conductor polls GHL every 6h per active cohort:
  per email: sent / delivered / opened / clicked / replied / unsubscribed / bounced
  per cohort: replies → conversations → bookings → won ($)
→ Dashboard: live cohort funnel view
→ Notion: rollup on each email entry (opens %, replies)
Day +30: auto-retro doc per cohort:
  best/worst subject per slot · reply-driving emails · SMS response ·
  time-to-first-reply · unsubscribe hotspots
→ /winback reads the last retro BEFORE writing the next set (skill amendment)
This closes the loop: every cohort writes better than the last, on evidence.
```

---

## LAYER 7 — Safety rails (missing piece #6 + #8)

```
KILL SWITCH   One dashboard toggle per cohort → conductor removes all cohort
              members from the workflow within one poll cycle. Un-killable
              sends already queued in GHL for that hour: accepted risk, ≤1 send.
FAILURE ALERTS  Send failures, bounce spikes (>5% cohort), unsubscribe spikes
              (>2%), conductor downtime → Lark/Telegram immediately.
SEED TEST     ← new (missing piece #8). Before the FIRST live cohort ever:
              full sequence (all 8 + SMS) sent to Rydel's own seed inboxes
              (Gmail, Outlook, iPhone SMS) on a compressed 1-email-per-hour
              schedule. You see every email as a lead sees it — rendering,
              tokens, spam placement, SMS formatting — before any lead does.
              Repeat whenever the template structurally changes.
NO-LLM SEND PATH  The conductor is deterministic code. Claude writes copy and
              summaries UPSTREAM of approval; nothing generative executes
              between your Launch click and a lead's inbox.
DRY-RUN MODE  Conductor flag: full run, logs every action, sends nothing.
              Used for cohort 1 rehearsal and after any conductor change.
```

---

## LAYER 8 — Build order (once this spec is approved)

```
1. Rydel approves THIS SPEC (structure, steps, rules, timings — the triple-confirm)
2. GHL template built by hand from Layer 2 in the Served sub-account
   (AU first; USA mirror after AU proves out). Screenshot walkthrough back for sign-off.
3. pd-conductor v1 (Railway): Notion read, preflight, GHL enrolment, alerts, dry-run
4. Dashboard PD section: review/approve, cohort list + summaries, fix list,
   Launch, kill switch (extends pd-shiproom-build.zip handoff)
5. Approval-hash + status-revert wiring (Notion ↔ conductor)
6. Seed test (Layer 7) — full compressed run to Rydel's inboxes
7. First live cohort under the new rails
8. Stats poller + retro generator (Layer 6) — can land after cohort 1 starts
9. served-winback + served-newsletter skill amendments (retro-reading, S2 ladder)
```

**Meanwhile:** the current August cohort (E1–E4 pushed to Notion, E5–Bump pending the
write gate) proceeds on the existing manual path — approve in Notion, load into GHL
by hand — so the schedule doesn't slip while the rails are built.

---

## RULINGS (locked 7 Aug — per Edith recommendations, Rydel confirmed)

1. Re-entry window: **6 months.**
2. US cohorts: **email-only** until TCPA-grade SMS consent capture exists.
3. Bump-day SMS: **default OFF**, per-cohort opt-in only.
4. Kill switch: **both** cohort-level and per-lead pause (same API call, scoped).
5. Seed inboxes: **Rydel to name addresses** (Gmail + Outlook + one iPhone number) — only ruling still open, needed before Layer 7 seed test, not before infra build.
6. Offer instrument: **bonus/deliverable-in-advance. No vouchers** — a voucher is a discount in costume. "voucher" added to the lock regex (engine fix).

## DOCTRINE AMENDMENTS (to be written into DECISIONS at engine-fix time)

**#110 amendment (conductor autonomy):** EDITH's "autonomous contact structurally impossible"
boundary is amended by the two-gate model: copy requires Rydel's Approved flip AND cohort
requires Rydel's Launch click. Post-Launch, the conductor executes the approved, hash-locked
sequence for up to 28 days unattended. This is sanctioned execution of pre-approved contact,
not autonomous contact. Any deviation from approved copy/schedule voids the sanction.

**#112 amendment (ladder):** New state **PD-ACTIVE**, distinct from S2. Contacts in the
Pitched and Drifted stage exit S2's general marketing freeze into the PD machine ONLY —
suppressed from newsletter/promos/all other sending while pd-active tag present. On cycle
completion: 14-day total quiet, then S4-WARM.
