# WHY THE MATCHER COULDN'T SEE POTTERY GREEN, AND WHERE SEVEN CONSULTS WENT

**2026-09-24 · served-cfo-agent · diagnose first, evidence from production**

---

## A · THE MATCHER — the hypothesis proved, plus one worse thing

**The hypothesis was right, with a refinement**: candidates are built from the
TRACKER only — its contact names (1,455) and its business column (594). The
**client roster (the Health tab, 38 actives) is never a name candidate**; it
is consulted only for the amount-corroboration boost. A client who exists on
the roster but has no tracker lead row is therefore invisible to the matcher
by construction.

Candidate lists produced on production, per payer:

| payer | candidates | verdict |
|---|---|---|
| Pottery Green Bakers Gordon | business index containing "pottery": **[]** · contacts containing "pottery": **[]** · roster actives containing "pottery": `['pottery green bakers gordon']` — **present, never consulted** | `unrecognised` — "nothing close enough to guess" |
| Fiona FITZGERALD | surname map: `fitzgerald → {62Thirty Cafe & Bar}` (unique) | `needs_review`, 62Thirty offered at strength 60 — correct behaviour, waiting on a ruling |
| Nirosha Jayasekara / NIROSHA JAYASEKARA | contact `Nirosha Dushani Jayasekara` (partial, 80) | `needs_review` — correct behaviour; case is already normalised away |

**The worse thing, found while proving it**: `_roster_index()` reads the
Health tab by POSITION and the positions are wrong. It takes `r[7]` as the
client's MRR — but column 7 is **Start Date**. Production evidence:

```
roster amounts: {'pottery green bakers gordon': 12022025.0}
```

That is the date **12-02-2025** with the punctuation stripped, held as
**$12,022,025.00 of monthly revenue**. Column 1 (Status) is read correctly;
the money column is off by three. Consequence: the amount-corroboration
signal (`_amount_ok`) has been comparing real charges against dates-as-dollars
— effectively dead, silently, for every match it was supposed to strengthen.
(Monthly Recognized Revenue is column 10; Contract Value is column 9.)

## B · THE APPOINTMENTS — ten consults, and the surfaces that show 0 and 3

**Ground truth, pulled live**: `GET /calendars/` lists **six calendars** —
Served Consultation (round-robin), Served Onboarding, two TEST calendars, and
two personal calendars. `GET /calendars/events` per calendar, today → +31
days, returns timestamps **with the +10:00 offset carried** (unlike the
per-contact endpoint, which is offset-less location-local — the #134 class
does not apply here).

Every event, 24 Sep → 1 Oct inclusive, Sydney time:

| when | title | status | calendar |
|---|---|---|---|
| Sep 24, 6:00 AM | Lilian Nguyen — Free Consultation | **cancelled** | Consultation |
| Sep 24, 8:30 AM | Jeff 24hrs Tesing | confirmed | **TEST** |
| Sep 24, 11:30 AM | Scott Cho — Free Consultation | confirmed | Consultation |
| Sep 24, 1:00 PM | Good Things Fremantle — Free Consultation | confirmed | Consultation |
| Sep 24, 3:00 PM | Nick Richard Allardice — Free Consultation | confirmed | Consultation |
| Sep 24, 4:00 PM | Simon — Free Consultation | **cancelled** | Consultation |
| Sep 24, 5:30 PM | Mohamad Daher — Free Consultation | confirmed | Consultation |
| Sep 25, 8:00 AM | Jeff 3Days Testing | confirmed | **TEST** |
| Sep 25, 9:00 AM | Lilian Nguyen — Free Consultation (rebooked) | confirmed | Consultation |
| Sep 25, 11:00 AM | Byrdi — Free Consultation | confirmed | Consultation |
| Sep 25, 2:30 PM | Koji — Onboarding | confirmed | **Onboarding** |
| Sep 25, 3:30 PM | Ling Ling Wong — Free Consultation | confirmed | Consultation |
| Sep 28, 8:00 AM | Dan — Follow Up | confirmed | Consultation |
| Sep 28, 1:00 PM | Lei Ye — Free Consultation | **cancelled** | Consultation |
| Sep 28, 2:00 PM | Luke Phat Panda — Free Consultation | confirmed | Consultation |
| Sep 28, 2:00 PM | Max Hoang Phuoc Pham | confirmed | Kalin's personal |
| Oct 1, 10:30 AM | Andrew Blake (Swan Hill RSL) — Follow Up | confirmed | Consultation |
| Oct 1, 3:00 PM | Reza — Follow Up | confirmed | Consultation |

Excluding cancelled (3), the TEST calendar (2) and onboarding (1): **12
booked sales events** — 9 titled Free Consultation, 3 titled Follow Up
(Dan, Andrew Blake, Reza), plus Max on Kalin's personal calendar inside the
consultation count. Rydel's 10 is inside this list; whether the three
follow-ups and Max's personal-calendar booking belong in "booked consults"
is a wording question the tiles now answer by SHOWING the list, not a data
gap.

**What each surface showed at the same moment**:

| surface | showed | of the 12 |
|---|---|---|
| pulse / home tile "booked calls 7d" | **3** (Good Things, Byrdi, Ling Ling) | 25% |
| SALES "next seven days" | **3** (same three) | 25% |
| travelling booked-in-window (7d) | **0** | 0% |

**The actual cause — from the named list**: *only some contacts pulled*.
Every surface reads the per-contact appointment cache
(`ghl:appt_cache`), which is warmed **only for contacts that already have a
tracker lead row** (171 contacts held). Scott Cho, Nick Allardice, Mohamad
Daher, Lilian, Dan, Luke, Max, Andrew, Reza simply are not in it — their
appointments were never fetched, because appointments were only ever fetched
*through* a tracker lead. Not the forward window, not statuses, not timezone,
not staleness: **the candidate set again** — the same failure shape as the
matcher, one layer up. (Travelling's extra zero is its booked-ON clock:
it counts bookings *created* in the window, and the cache's `dateAdded`
values for these mostly predate it.)

## C · One source?

Technically yes — all three surfaces read the same cache — which is exactly
why all three are wrong together. "One source" is only a virtue when the
source is complete. The fix is a **calendar-level** source (every calendar,
every user, all statuses, Sydney-parsed), synced on the CRM loop, that every
surface reads; the per-contact cache stays for what it is good at (the
consult field on a lead's own card).

## What this wave builds

1. venue names from the ROSTER become first-class matcher candidates,
   normalised (&/and, case, suffixes), evidence-tagged — auto-match stays
   exact-evidence only; the roster column defect is fixed and pinned.
2. the three payer aliases applied under Rydel's rulings, journaled.
3. `appointments.py` — the calendar-level source of truth; every booked-calls
   surface reads it; every tile states its window in words; cancelled and
   test bookings shown separately, never inside the count.
4. the status-stale rule (paid in the last 60 days but zero/expired MRR —
   Pottery Green is the first finding) and the full GHL↔tracker↔dashboard
   sweep.
