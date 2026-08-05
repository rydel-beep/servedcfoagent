---
name: served-winback
description: >
  Writes the Pitched & Drifted win-back sequences for leads who were
  pitched, said yes on the call, then stalled and were dragged into the
  "Pitched and Drifted" stage of the Served Pipeline. Trigger on /winback,
  or whenever Rydel asks to write, draft, rework, or QA pitched-and-drifted
  emails, PD emails, win-back or re-engagement emails for stalled leads,
  the drifted-lead sequence, or the offer email for a drifted cohort —
  even without saying "skill" or "/winback". Pulls proof live from the
  Meta/Google Wins DBs and logged testimonials, maps each email to a stall
  objection, and ends the cycle with a bonus-stacked offer under the global
  discount lock. BOUNDARY: only for contacts in the Pitched and Drifted
  stage of Served's own pipeline. General lead-list nurture is
  served-newsletter; client campaigns in client sub-accounts are the
  served-email agent — never this skill.
---

# Served Win-Back Engine — `/winback`

The recovery layer of the sales engine:

Pitch → YES on the call → stalls → dragged to **Pitched and Drifted** →
**THIS SEQUENCE** → claims the offer → back on a call → closed.

Same discipline as `/episode`, `/ad`, and `/newsletter`: locked, versioned
standards so quality never drifts. **This skill writes; it never sends.**
Sending, tagging, and automation live in GHL and are wired by Mark/Tristan
per `references/ghl-pd-spec.md`.

## Who the reader is (never forget this)

Not a cold lead. Not a subscriber. This person sat through the pitch, heard
the price, and said yes — then something killed the deal after the call.
They already know what Served does. Re-pitching the package insults them;
pretending this is a generic newsletter insults them more.

In Hormozi's value equation, the variable that collapsed post-call is
**perceived likelihood of achievement** (doubt crept in) or **effort &
sacrifice** (it started feeling like work), or an external blocker (cash
flow, partner, timing). The sequence exists to restore certainty with
receipts, shrink perceived effort by showing the machine, and then remove
the last excuse with an offer. Every email is written to one of those jobs.

## Command

```
/winback                          full cycle for the current cohort
/winback --cohort pd-2026-08      full cycle for a named cohort tag
/winback email N                  one email only (1–7, or "bump")
/winback offer                    offer email + bump only
/winback --round 2                re-entry variant (lead drifted twice — all-new angles)
```

---

## HARD PREREQUISITES — check before writing a word

1. **Read the voice standard LIVE, never from memory:** open
   `/mnt/skills/user/served-episode/SKILL.md` and re-read **Standard 5
   (Voice)** and the CTA locks. Everything banned there is banned here.
2. **Read the newsletter locks LIVE:** open
   `/mnt/skills/user/served-newsletter/SKILL.md` and re-read PROOF RULES,
   CTA LOCKS, and the SEGMENTATION LADDER. This skill inherits all three;
   the PD-specific deltas below override only where stated.
3. **Pull proof live.** Query the Meta Wins DB
   (`2e68984c-0474-80bf-bcd4-000b5e1d403f`) and Google Wins DB
   (`834a6207-ddfd-46b1-9d76-9f0c6d36278f`). Never cite a number from
   memory. Testimonial quotes/snippets only from assets Rydel has logged or
   linked — never reconstructed, never paraphrased into stronger claims.
4. **Dedup check, both directions.** Query the Email Library DB
   (`3118984c-0474-8002-bb33-000b0cbfd361`) for the last ~10 sends AND all
   prior PD cohorts. No repeated openings, no repeated angles within a
   4-week window, and no email in this sequence may reuse the copy of a
   currently-running ad word-for-word — PD leads came through the ad
   funnel and have likely seen the ads. Proof may repeat across channels;
   copy may not.
5. **Confirm the merge fields exist** (venue name, closer name, pitched
   package, stall reason, offer deadline) per `references/ghl-pd-spec.md`.
   Drafts use tokens only. If a token's field isn't confirmed live in GHL,
   flag it in the draft header — never invent a value.
6. **Exclusions:** if any contact in the cohort is a churned client (S3),
   they do NOT enter this sequence — proof emails to churned clients are
   salt, not social proof (newsletter S3 rule). Flag them to Rydel for
   manual handling.
7. **Pull the cohort's offer from the Monthly Offers DB**
   (`collection://e7a586f4-7487-4f40-aeea-35e423dbe713`, under the
   Pitched & Drifted — Win-Back Hub). Email 7 is written from the
   **Approved** row for the cohort's month — construction, inclusions,
   deadline length, claim URL. No Approved row for the month → STOP and
   ask Rydel to set it. This skill never invents an offer.

---

## SEQUENCE ARCHITECTURE (locked v1 — 4-week cycle)

Two sends a week for three weeks, then the offer week. One email = one job.

| # | Week/Day | Job | Objection targeted |
|---|----------|-----|-------------------|
| 1 | W1 Tue | Re-open: context frame + first receipt | (frame) |
| 2 | W1 Thu | Proof + technique | "Will it work for MY venue?" |
| 3 | W2 Tue | Proof + technique | Price / cash flow — the ROI math |
| 4 | W2 Thu | Proof + technique | Timing / "after X" — cost of waiting |
| 5 | W3 Tue | Proof + technique | Burned before / trust — what they see weekly |
| 6 | W3 Thu | Proof + technique | "We'll do it ourselves" — the gap |
| 7 | W4 Tue | **THE OFFER** | The last excuse |
| B | W4 Fri | 9-word bump | — |

- Send time 10:00 contact-local unless LEARNINGS says otherwise.
- **If `stall_reason` is populated for the contact/cohort majority, reorder
  so the dominant objection lands at Email 2.** The map is a default order,
  not a cage — coverage of all five objections across 2–6 is the lock.
- Cohorts are monthly (`pd-YYYY-MM`). A lead dragged in mid-cycle starts at
  Email 1 on the next send day — nobody ever enters at Email 4.
- After the bump with no action: sequence ends. GHL moves them to long-term
  nurture (S4-WARM) and opens one manual-touch task for the closer. The
  sequence never loops.

---

## EMAIL 1 — THE RE-OPEN (the announce question, settled)

**Name the situation, then deliver a full proof piece in the same email.**
Not a housekeeping email, not a silent add. Two to three lines of honest
frame, then receipts.

Why (this is the locked reasoning, don't relitigate it per cohort):
- A silent add reads as generic marketing — exactly what a stalled lead
  filters out — and confused recipients hit spam, which taxes deliverability
  for the entire Served sub-account, not just this list.
- The frame converts the relationship from "salesperson chasing me" to
  "operator showing receipts." That reframe IS the strategy.
- Hormozi: lead with give, and tell them the deal. The frame sets the
  expectation that opens emails 2–7: value, not chasing.

**The frame (principles, one worked example — never a pasted script):**
- Name it plainly, zero blame, zero apology: they spoke with {{CLOSER_NAME}},
  it made sense, the timing didn't line up.
- State the deal: for the next few weeks, roughly twice a week, what's
  working right now in venues like theirs — real spend, real returns. Use
  it themselves or watch how it's done.
- One door-open line. No CTA, no link, no ask.
- Then the first case study, full anatomy, same email.

Example frame energy (adapt, never paste):
> You spoke with {{pd_closer}} a few weeks back about {{VENUE_NAME}}. It
> made sense on the call, and then life got in the way — that's fine, it
> happens. So here's what we'll do instead of chasing you...

**Banned in Email 1 (and everywhere):** "newsletter", "subscribe/d",
"just checking in", "following up", "circling back", "I know you're busy",
apology framing, guilt framing, and any re-statement of the package or
price they were pitched.

---

## VALUE EMAIL ANATOMY (Emails 1–6)

- **Subject:** 3 options, NUMBER+CLAIM, under ~50 chars, no clickbait
  withholding, no ALL CAPS, no emoji. Rydel picks or the top one ships.
- **Preview:** under ~80 chars, adds to the subject, never repeats it.
- **Open:** first line lands straight in the venue or the number. Zero
  throat-clearing.
- **The case:** venue (named ONLY if it passes the active-client rule —
  cross-check live; otherwise venue-type + city), timeframe, spend in →
  revenue out. Dollar-in-dollar-out is the house language. ONE proof point
  per email, max. The same client cannot anchor two emails in one cohort.
- **The technique:** teach the actual mechanism behind the result. Give it
  away completely — the 99:1 give:ask ratio is the point. A reader who
  could DIY from this email and doesn't is a reader who now knows exactly
  what they'd be buying.
- **The close:** one quiet door-open line, varied across the sequence,
  never needy. No booking link exists before Email 7 — that lock is
  absolute. "Hit reply" is the only permitted ask in value emails, used at
  most twice across the whole sequence (a reply is a raised hand; GHL
  routes it to the closer).
- **Format:** plain-text feel per the newsletter standard — short paragraphs,
  hard breaks, no banners, no image blocks. Reads like a person emailed
  them after service. **Sender is THE SERVED TEAM — locked.** Sign-off
  `— The Served Team`, never an individual's signature. The pitch call was
  run by a closer ({{pd_closer}} — e.g. Kalin or Coby), so the call is
  ALWAYS referenced in third person: "your call with {{pd_closer}}" /
  "when you spoke with {{pd_closer}}". BANNED: "when we spoke", "our
  call", or any first-person framing that implies the sender personally
  ran the pitch.
- **Length:** 120–220 words. Hard ceiling. If it needs more, the angle is
  wrong — recut, don't extend.

## EMAIL 7 — THE OFFER (Grand Slam, under the discount lock)

The job: remove the last excuse and get the claim. Anatomy:

1. **Re-anchor their outcome** — the thing they said yes to. One line.
2. **The offer comes from the cohort's Monthly Offers row** — its
   construction, inclusions, deadline length, and claim URL. The skill
   writes the copy AROUND the offer; it never invents or modifies the
   offer itself. NEVER a discount — the GLOBAL DISCOUNT LOCK from the
   newsletter skill applies in full. Approved constructions for that DB:
   - **Deliverable-in-advance:** a named, real asset built for their venue
     before they pay (e.g. the Foundation Market Intelligence report),
     walked through on the call, theirs either way. Mirrors the approved
     "no pitch, you keep the plan" device — never drifts into "free
     audit" language.
   - **Bonus stack:** named add-ons with real standalone value attached to
     proceeding by the deadline.
   - **Priority/slot mechanics:** only when the constraint is real.
   - The $1,000 voucher ONLY if Rydel has ruled it consistent with the
     discount lock (see ONE-TIME SETUP).
3. **Risk reversal:** only mechanics that actually exist in the current
   sales policy. Never invent a guarantee.
4. **True deadline:** {{OFFER_DEADLINE}} = send date + the offer row's
   Deadline (days), enforced by the GHL automation, honored absolutely. Expired means expired — one broken
   deadline poisons every future cohort's scarcity.
5. **One CTA, claim-framed.** Single link ({{CLAIM_URL}}), repeated max
   twice. CTA locks inherited: "free audit", "book a strategy call", and
   "hop on a quick call" are banned in every form. Claim language: pick a
   time, we bring {{deliverable}}, it's yours either way.
6. **Length:** 180–280 words. The one place a slightly longer email earns
   its keep.

**Antithesis cap:** the "it's not X — it's Y" construction is capped at ONE
across the entire 8-touch sequence, usable only in Email 7, only as a
genuine earned kill-line. Zero elsewhere.

## THE BUMP (W4 Fri)

Nine-word-email spirit: under ~25 words, question form, references
{{VENUE_NAME}}, references the deadline. No new arguments, no proof, no
guilt. Either link-free or the single claim link — nothing else.

---

## PROOF RULES (inherited + PD deltas)

All newsletter PROOF RULES apply verbatim: churned wins anonymised by
venue type, pax→revenue multiplier (×3–4) dine-in only, never fabricate —
no proof available means write without proof, never invent. Report windows
framed as snapshots of live campaigns, never "campaign ended." Hanmades
stays anonymised.

**NAMING (Rydel's ruling, Aug 2026):** real client names are the DEFAULT —
venue name plus contact first name where known ("Ashley from Bluebells").
Where clearance isn't confirmed, keep the copy on venue-type ("a Thai
restaurant") and add a **CLEARANCE line in the entry's NOTES** listing the
real venue so Rydel can confirm and name it at review. Rydel is the
clearance gate — nothing sends before he flips the status, so uncertain
names never leave the building. Never invent a contact name.

**BANNED PROOF — never use in any PD email:**
- Sugbo Grill (all campaigns) — banned by Rydel, Aug 2026.

**ONE STORY PER EMAIL** — each value email anchors on ONE proof story from
ONE client, and no client anchors two emails in a cohort. Single
exception: the Fit email (E2) may use up to three one-line contrasts from
three different clients, because unlikeness IS its argument.

PD additions:
- **Every number in every draft carries a trace** in the NOTES block: the
  Wins DB row (or testimonial/call-record page) it came from. Untraceable
  number = the email doesn't ship. This is the anti-hallucination contract.
- **Nearest-match proof beats biggest proof.** Pick the win closest to the
  reader's venue type/suburb over the flashiest multiple. A cafe owner
  trusts a cafe result more than a 106x events number.
- Season words stay market-neutral ("busy season", not a hemisphere's
  season) so cohort copy can mirror across AU/US pipelines.

## CLIENT VOICE EMAILS (testimonial-led)

At least one email per cohort should simply be *hearing from a client* —
their words carry it, we frame minimally. Rules:
- Quotes are the client's **exact recorded words** from a logged source
  (testimonial video, call record, review) — never tightened, improved,
  or reconstructed from memory. Trace the source page in NOTES.
- Structure: one line of setup → the quote, visually set apart → the one
  tracked number behind it → out. Under 150 words. No technique section.
- Only business/marketing facts around the quote — never the client's
  personal backstory, even if logged.
- If no logged testimonial exists for the cohort, don't fake the format —
  run a standard proof email and flag the gap to Rydel.

## AUDIENCE & SUPPRESSION (states the contract on every draft)

Audience: contacts in the **Pitched and Drifted** stage carrying
`pd-active`, entered ONLY by manual sales-team drag. While `pd-active`,
the contact is suppressed from ALL other Served email — no newsletter
packages, no tips, no broadcasts. One voice at a time. Exits (booked /
completed / unsubscribed) per `references/ghl-pd-spec.md`. Every draft
header states audience + suppression. Proposed ladder status: S2-DRIFTED,
to be written into the served-newsletter ladder at setup.

---

## OUTPUT FORMAT (the draft in chat)

```
WIN-BACK CYCLE — cohort pd-YYYY-MM
Cohort size: N | Stall reasons known: [mix or "not captured"]
Schedule: W1 Tue [date] → W4 Fri [date] | Offer deadline: [date]
Audience: PD stage / pd-active only. All other sends suppressed. S3 excluded.
SEND-GATED — do not load until Review DB status = Approved AND GHL wiring
confirmed per ghl-pd-spec.md

── EMAIL 1 — RE-OPEN ────────────────────────
Subject options: 1. / 2. / 3.
Preview: ...
[body — tokens for all merge fields]
— The Served Team

── EMAIL 2 — [objection] ────────────────────
...

── EMAIL 7 — OFFER ──────────────────────────
...

── BUMP ─────────────────────────────────────
...

---
NOTES:
- Objection coverage: E2=[..] E3=[..] E4=[..] E5=[..] E6=[..]
- Proof trace: [email # → venue/venue-type → numbers → DB row link]
- Angle log (for Email Library): ...
- Tokens used: [list — all confirmed live in GHL? Y/flag]
- Offer row: [Monthly Offers page link] | Deadline: [date]
```

## APPROVAL & LOGGING — push on approval ONLY

Draft in chat → Rydel voice-checks → on "yep":

1. Create one page per email in the **PD Email Review DB**
   (`collection://f38d3581-8844-4249-aea2-8e041be37e41`, under the
   Pitched & Drifted — Win-Back Hub). Properties: Cohort, **Week
   (Week 1–4)**, Email (E1–E7 / Bump — the objection is encoded in the
   option), Status `Rydel Review` (NEVER auto-approved — Rydel flips it),
   Scheduled, Subject (chosen), Preview. Full body + notes go in the page
   content. **Relations are mandatory:** any email citing a number relates
   its `Source Wins (Meta)` / `(Google)` row(s); E7 relates its
   `Monthly Offer` row. No resolvable relation → STOP and ask. Never
   guess a relation.
   **ENTRY NAMING (locked):** titles read month + week + number + plain
   name — `August · Week 1 · Email 1 — The Re-Open`. The offer email gets
   the distinguished entry: `🎁 AUGUST OFFER · Week 4 — <offer name>
   (Email 7)` with the 🎁 page icon. Icons: ✉️ value emails, 🗣️ Client
   Voice, 🎁 offer, ⚡ bump. Every entry carries a CLEARANCE line in NOTES
   for any client referenced.
2. Log the angle set to the Email Library DB
   (`3118984c-0474-8002-bb33-000b0cbfd361`) tagged `pd` for cross-skill
   dedup.
3. Remind Rydel the cohort goes to Mark/Tristan for loading per
   `references/ghl-pd-spec.md`. This skill never pushes to GHL.

Never write to Notion without approval. Never send anything.

## PRE-SHIP CHECKLIST (run silently before presenting)

- [ ] Episode Standard 5 + newsletter locks re-read this session
- [ ] All five objections covered across E2–E6; reorder applied if
      stall_reason data exists
- [ ] One proof point per email, all traced to DB rows; naming rules pass
- [ ] No booking link before E7; "hit reply" used ≤2 times; one CTA in E7
- [ ] Zero banned phrases; zero discount language; antithesis count ≤1
      (E7 only)
- [ ] Subjects <50 chars ×3 per email; previews add, not repeat
- [ ] Length ceilings hold (value ≤220w, offer ≤280w, bump ≤25w)
- [ ] Deadline is real, matches the GHL automation, and is enforceable
- [ ] Angles deduped vs Email Library + prior PD cohorts + running ads
- [ ] All tokens confirmed or flagged; audience + suppression header present
- [ ] S3 contacts excluded from cohort

## LEARNINGS (data-backed — last review: none yet)
<!-- Auto-rewritten when Rydel pastes or pulls GHL stats per cohort: opens,
     clicks, replies, claims, booked calls, closed revenue. Derive
     enforceable rules (subject shapes, objection order, offer
     constructions that claim) and write them here. The writer obeys this
     block once populated. Primary metric: re-booked calls per cohort.
     House metric: dollars recovered per cohort — dollar in, dollar out,
     applied to our own win-back. -->
- No cohort data yet. After cohort 1 completes, pull stats and populate.

## ONE-TIME SETUP (flag until done, then delete this section)

- [x] Notion hub live: Win-Back Hub page + PD Email Review
      (`collection://f38d3581-8844-4249-aea2-8e041be37e41`) + PD Monthly
      Offers (`collection://e7a586f4-7487-4f40-aeea-35e423dbe713`)
- [ ] GHL build live per `references/ghl-pd-spec.md` (Mark/Tristan — Asana)
- [ ] August offer set + Approved in the Monthly Offers DB
- [ ] Ladder amendment (S2-DRIFTED) written into served-newsletter SKILL.md
- [ ] Rydel's ruling: $1,000 voucher as PD offer — consistent with the
      discount lock, or bonus-constructions only?
- [x] Sender identity locked: THE SERVED TEAM (calls referenced via
      {{pd_closer}} in third person — ruled by Rydel, Aug 2026)
- [ ] Timeline Dashboard PD panel live (queue + cohort funnel + open rates)
