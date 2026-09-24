# GHL ↔ TRACKER ↔ DASHBOARD SWEEP — 2026-09-24

Trailing 90 days (2026-06-26 → 2026-09-24) unless a section says otherwise. Read-only; every mismatch carries a cause class.

## 1 · Contacts and clients
- GHL contacts: **1469** · tracker rows: **1458** · roster clients: **60** (38 active)
- email-linked tracker↔GHL: **1264** of 1374 tracker emails (110 tracker-only, 191 GHL-only) — cause: **id-unlinked** (historic rows predate the CRM; new rows link by email)
- roster clients with NO tracker lead row (44) — cause: **unfilled-column / pre-tracker client**: 1st Edition Bar, 62Thirty Cafe, Abou George Pizza, Akuna Cafe, Alice Springs Brewing Co, AllSpice Thai Restaurant, Asian Streat, At Thai, Bar Elvina, Bluebells Takeaway, Bunni Beez, Casa de Amor…

## 2 · Leads (90d)
- tracker lead rows: **266** · GHL opportunities created: **249**
- GHL leads missing a tracker row: **0** — cause: **r-gap-window / unfilled-column** (each already a Piolo package line): 

## 3 · Qualified (rule inputs present?)
- of 266 leads: revenue band filled **261** (98%) · market filled **266** (100%) — blanks are cause: **unfilled-column** (the qualified rule cannot fire on a blank)

## 4 · Appointments (calendar window −7d → +35d)
- calendar events held: **36** — booked **27**, cancelled **6**, test-calendar **2**
- tracker rows marked SET (all time): **528** · the tracker's Set Date column has been empty since April — cause: **unfilled-column**; the CRM calendars are the booked source (#162)

## 5 · Shows (t30, the one show-basis rule)
- confirmed **6** · unmarked **6** of 15 due — rate 40% (upper 80%) — unmarked consults are cause: **status-vocabulary** (nobody recorded an outcome; the attendance surface lists them)

## 6 · Closes (90d, tracker vs GHL stage vs payments)
- detection ledger: **26** (3 confirmed, 23 detected)
  - 2026-09-23 · **Koji** · CONFIRMED · seen by ghl stage, payment, stage recorder, tracker · missing: nothing · cause: **aligned**
  - 2026-09-11 · **William Cooney** · CONFIRMED · seen by ghl stage, payment · missing: contract value · cause: **r-gap-window / unfilled-column**
  - 2026-09-11 · **Harman singh** · CONFIRMED · seen by ghl stage, payment · missing: contract value · cause: **r-gap-window / unfilled-column**
  - 2026-09-09 · **Orlando Rinaldi** · DETECTED · seen by ghl stage · missing: contract value, a matched payment · cause: **payer-alias**
  - 2026-08-28 · **Sweetapple Jaraslak** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-27 · **Michael Pulvirenti** · DETECTED · seen by ghl stage · missing: contract value, a matched payment · cause: **payer-alias**
  - 2026-08-24 · **Lucas Reid** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-21 · **Maulik Chaudhari** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-20 · **Cyrus Platon** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-18 · **Emmat** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-18 · **Tesla Zhong** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-14 · **Tong Ou** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-14 · **Milad Alizadeh** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-11 · **Mik V** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-10 · **Alyssa Grima** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-10 · **Arthur Gruselle** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-08 · **Christina Theravanish** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-06 · **Johnny Ibra** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-08-01 · **CHAAN ฉันท์** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-07-31 · **Kristeen Hammond** · DETECTED · seen by ghl stage · missing: contract value, a matched payment · cause: **payer-alias**
  - 2026-07-30 · **Tony Thai** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-07-30 · **Terry Yu** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-07-30 · **Ashley Clarke** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-07-29 · **shalini bhargava** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-07-28 · **Sarah Waters** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**
  - 2026-07-28 · **Tommy Sun** · DETECTED · seen by payment · missing: contract value, the CRM record · cause: **r-gap-window / unfilled-column**

## 7 · Cash (Stripe vs attachment vs the tracker column)
- matched payments: **57** · unattached: **0** ($0.00) — every unattached row is cause: **payer-alias** (one click each)
- tracker Cash Collected cells filled: **68** — blanks on won rows are cause: **unfilled-column** (Piolo package)

## 8 · Contract values (90d closes)
- closes: **12** · missing a contract value: **1** (Arthur Gruselle) — cause: **unfilled-column**

## 9 · Client status and MRR (the standing rule)
- status-stale findings: **2** — cause: **roster-stale**
  - **Pottery Green Bakers Gordon** paid $1,760 (2026-09-20) + $1,760 (2026-08-20) while the roster says term ended 06-02-2026 — charge ids ch_3UHbrjBjA5FwcLGQ1V9i5biW, ch_3U6N2oBjA5FwcLGQ18vtb0oZ
  - **Texas charcoal chicken** paid $3,300 (2026-08-14) while the roster says status is 'Finished' — charge ids ch_3U0rKcBjA5FwcLGQ0INtjQ8T

