# PD GHL Build Sheet — v2 EVERGREEN

**Supersedes:** the cohort-dated build sheet (v1) and the dated-cohort mechanics of
MASTER-SPEC v1.1 Layer 2. Authority: MASTER-SPEC-v1.2.md (ruled 7 Aug — "go evergreen").

**BUILD STATE RULE (absolute): everything below is built in DRAFT / UNPUBLISHED state.
NO publish, NO sends, NO test sends to real contacts. Publish happens only after
(1) screenshot walkthrough sign-off from Rydel and (2) the seed test (§8) passes.**

The GHL API cannot create workflows — this is a hand-build in the GHL GUI,
AU sub-account first (pipeline `JJQLCr1fl7OHyrpRwSJp`). USA mirror
(`ieMQNO2paLTKp2HRLETP`) only after AU proves out, and **email-only** (Ruling 2).

---

## 1. Custom fields (contact-level — create first)

| Field | Type | Set by | Notes |
|---|---|---|---|
| `pd_closer` | Dropdown | Sales at stage-drag (**mandatory**) | Values = current closer roster. Never free-text — a guessed name is worse than none. |
| `pd_stall_reason` | Dropdown | Sales at stage-drag | `price` / `timing` / `trust` / `other`. Selects the E7 SMS angle. |
| `pd_pitched_package` | Dropdown | Sales at stage-drag | Firestarter / Growth Pro / Scale Engine / custom |
| `pd_pitch_date` | Date | Sales at stage-drag | Enables future time-specific copy (E1 v3.1 lock note) |
| `pd_offer_deadline` | Date | **Workflow, at enrolment** = entry + 28 days | The ONLY deadline source. Copy tokens read this field directly. Verify it renders human-readable ("8 September") in email + SMS — if it renders ISO, add a formatted text twin field the workflow writes at the same step. |
| `pd_last_completed` | Date | Workflow, at cycle completion | Drives the 6-month re-entry guard (date math on a field — GHL can't do tag-age math). |

**RETIRED — do not create:** `pd_cohort` field, `pd-{YYYY-MM}` cohort entry tags,
anything Launch/cohort-shaped.

## 2. Tags

`pd-grace` · `pd-active` · `pd-email-only` · `pd-replied` · `pd-bad-email` ·
`pd-completed-{YYYY-MM}` (audit stamp at completion; the guard runs on
`pd_last_completed`, the tag is human-readable history).

**Suppression contract:** `pd-active` present = excluded from ALL other Served
sending. Build step: audit every existing Served workflow/campaign and add the
`pd-active is not present` filter. This is part of THIS build, not a later nicety.

---

## 3. Workflow A — "PD — Grace Window" (entry gate; replaces the Launch ceremony)

**Trigger:** Opportunity stage changed → *Pitched and Drifted* (AU pipeline).

```
1. GUARD — re-entry:  pd_last_completed within last 183 days?
     YES → alert sales channel: "{{contact.name}} — manual follow-up only,
           PD used {{contact.pd_last_completed}}" → END (workflow never arms).
2. GUARD — suppression:  unsubscribed / DND / S3 → END quietly.
3. Add tag pd-grace.
4. ALERT (Lark/Telegram sales channel):
   "{{contact.name}} ({{contact.venue_name}}) enters the PD sequence in 48h —
    reply/book/move them out of the stage to stop it. Closer: {{contact.pd_closer}}."
5. WAIT 48 hours.
6. RE-CHECK (any true → remove pd-grace → END quietly):
     replied since entry · appointment booked · opportunity moved out of the
     stage · opportunity won/re-opened.
7. PREFLIGHT branches (GHL-native; conductor is deferred):
     a. Email invalid/bounced        → tag pd-bad-email + alert + END.
     b. venue_name empty             → alert "fix + re-drag" + END (no
                                        "Hi , about your venue" ever sends).
     c. Mobile empty OR no SMS consent basis (prior SMS thread / mobile
        knowingly provided)          → tag pd-email-only (sequence skips SMS).
     d. Timezone empty               → set default AEST + alert flag.
     e. In another active Served sequence (any seq-* / *-active tag)
                                     → alert + END (native tag check is the
                                        evergreen source; the API-based
                                        active-workflow check was conductor scope).
8. ARM:  set pd_offer_deadline = now + 28 days
         → remove pd-grace → add pd-active
         → enrol into Workflow B.
```

## 4. Workflow B — "PD — Sequence (Evergreen)" (frozen infrastructure)

All emails 10:00 recipient-local (contact timezone, AEST fallback).
Relative timing from enrolment day (D0) — no weekday anchors, no cohort dates.

| Day | Step | Slot |
|---|---|---|
| D0 | E1 | Re-Open |
| +2 | E2 | Fit |
| +7 | E3 | Price/ROI |
| +9 | E4 | Timing / cost of waiting |
| +14 | E5 | Client Voice (Ashley, Bluebells) |
| +16 | E6 | DIY Truth |
| +21 | E7 | **OFFER — Venue Growth Blueprint (standing offer)** |
| +21, 13:00 local | OFFER SMS | ≤300 chars · ends "Reply STOP to opt out" · send-window restriction 09:00–19:00 local, weekdays only (GHL step-level window; if +21 lands on a weekend the SMS waits for the next weekday window) · **skipped entirely if tag pd-email-only** |
| +24 | BUMP | Last nudge (bump-day SMS is NOT built — Ruling 3 default-OFF and evergreen has no per-cohort opt-in; adding it later = structural change = re-run seed test) |
| +28 | DEADLINE | `pd_offer_deadline` passes; no send — the date lives in E7/Bump copy via the field token |

**Closer branch** on every email that references the call:
`pd_closer` set → "you spoke with {{contact.pd_closer}}" · empty → "you spoke
with our team". Never a guessed name.

**Hard caps:** 8 emails + 1 SMS per lead per cycle. Ever.

**Completion branch** (sequence ends, no conversion):
```
remove pd-active
→ contact note: "PD completed {date}, no response"
→ set pd_last_completed = today · add tag pd-completed-{YYYY-MM}
→ WAIT 14 days (TOTAL silence — the pd-active suppression filter has lifted,
  so verify no other workflow picks them up inside the window; if needed keep
  a pd-quiet tag for the 14 days and filter on it too)
→ status S4-WARM → standard newsletter cadence resumes.
```

## 5. Exit paths (wire ALL of these; any fires at any point)

```
1. REPLY (email or SMS)  → remove from Workflow B instantly
                         → alert closer (Lark/Telegram) with lead + reply text
                         → tag pd-replied; stage untouched until the closer moves it
2. CALL BOOKED           → exit instantly → alert closer → move to booked stage
3. OPP RE-OPENED / WON   → exit instantly (sales took over)
4. EMAIL UNSUBSCRIBE     → exit + global suppression honoured across ALL Served sending
5. SMS "STOP"            → SMS opt-out flag only; email sequence continues
6. HARD BOUNCE           → exit + tag pd-bad-email + alert (fix list is the alert
                           channel until a dashboard section exists)
7. PAUSE                 → per-lead: remove from workflow (manual or API — same
                           call the old kill switch used, scoped to one contact).
                           Global: unpublish/pause Workflow B (leads hold in place).
```

## 6. Compliance checklist (verify inside the template before sign-off)

- [ ] Working unsubscribe link renders in every email (GHL native footer) — Spam Act 2003
- [ ] Sender identity accurate: Served Marketing / The 97 Group Pty Ltd
- [ ] SMS ends "Reply STOP to opt out"; opt-outs actioned immediately + logged
- [ ] SMS step window 09:00–19:00 recipient-local, weekdays only
- [ ] No SMS without consent basis (Workflow A step 7c enforces)
- [ ] USA mirror: SMS steps ABSENT (not disabled — absent) · postal address in
      footer · prompt opt-out (CAN-SPAM/TCPA)

## 7. Copy loading

Source of truth: Notion **PD Email Review DB** (`f38d3581-8844-4249-aea2-8e041be37e41`).
Only rows at **"Approved — ready for GHL"** may be pasted into the template.
Current set: the 8 pages on **v3.1 EVERGREEN** (deadline_weekday token removed;
copy reads `{{pd_offer_deadline}}` directly). Discount lock applies to all copy:
no discounts, no vouchers (Ruling 6).

Refresh cadence: **QUARTERLY** — proof screenshots re-pulled from Wins DBs,
re-approve, re-paste. Any Notion edit after approval reverts the row to
"Rydel Review" (approval-hash rule) — never paste from a non-Approved row.

## 8. Sign-off gates (in order — nothing skips)

```
GATE 1  Both workflows built in DRAFT → screenshot walkthrough → Rydel sign-off.
GATE 2  SEED TEST: full sequence (8 emails + offer SMS) to Rydel's seed inboxes
        (Gmail + Outlook + one iPhone number — Ruling 5 STILL OPEN, Rydel to
        name addresses) on a compressed 1-email-per-hour schedule.
        Checks: rendering, closer-branch both ways, {{pd_offer_deadline}}
        renders human-readable, spam placement, SMS formatting + STOP line.
        Repeat whenever the template structurally changes.
GATE 3  Rydel publishes. First real leads flow through the grace window.
```

## 9. Standing operations (replaces the monthly cycle)

- **Weekly:** read grace-window alerts + reply alerts. That's the whole ritual.
- **Quarterly:** proof refresh + 3-number check — replies, bookings, unsubscribes.
- **Deferred until the segment earns it:** pd-conductor (GHL native handles
  enrolment/dates at current volume), dashboard PD section, 6h stats poller,
  auto-retro. Re-entry trigger for these: PD volume or reply flow makes the
  weekly alert-read insufficient.

## 10. Open items (flagged, not blocking the DRAFT build)

1. **Ruling 5** — seed inbox addresses from Rydel (blocks Gate 2, not Gate 1).
2. `{{pd_offer_deadline}}` human-readable render — confirm in GHL during build;
   fallback = formatted text twin field (§1).
3. Weekend landings for email offsets: default = send at 10:00 local on the
   offset day whatever the weekday (spec gives pure day offsets). If Rydel wants
   weekday-only emails, that's a spec amendment, not a builder's call.
4. 14-day post-cycle silence enforcement across other workflows (§4 completion
   branch note) — verify during the suppression-filter audit (§2).
