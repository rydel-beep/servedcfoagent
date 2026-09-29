# Payment-matching proposals — 29 Sep 2026 (#170, Rydel ruling 3)

**PROPOSALS ONLY. Nothing here is applied.** Each row becomes an alias only when
Rydel confirms it. Every proposal cites its evidence. A resemblance of names
alone is marked **weak**.

Sources (all read-only):
- Stripe: every unmatched succeeded charge from 31 Mar 2025 to 29 Sep 2026
  (`scripts/unmatched_history_probe.py`)
- The tracker's won rows (`scripts/proposal_tracker_probe.py`)
- Xero: paid receivable invoices (the XERO connector)

## A · Unmatched Stripe payers: 22 payers, 103 charges, $226,928.20

| # | Stripe payer | Charges · total · span | Evidence | Proposed client | Strength |
|---|---|---|---|---|---|
| 1 | norvin Acabo | 28 · $30,800 · Apr 25 → Apr 26 | Xero invoices to "Norvin Acabo" (same person); no business named | **needs your name** | — |
| 2 | Adrian Sheather | 10 · $27,500 · Apr 25 → Jan 26 | email @risingsunworkshop.com | Rising Sun Workshop | strong (domain) |
| 3 | Prashant Sharma | 4 · $19,505.40 · Oct → Dec 25 | gmail, "Subscription update" only | **needs your name** | — |
| 4 | (unnamed customer) | 7 · $15,165 · Oct 25 → Jan 26 | no name, no email | **needs your name** | — |
| 5 | Thuong Tran | 2 · $13,750 · Mar → Apr 26 | email @ourtook.com | the business behind ourtook.com | medium (domain, name unknown) |
| 6 | Xuan Hieo Nguyen | 3 · $13,747.80 · Aug → Oct 25 | matcher: TRITON SEAFOOD MARKET on first name only; that tracker row isn't won | none | weak |
| 7 | Hannah Tamayo | 6 · $13,200 · Oct 25 → Mar 26 | email @hanmadesbakehouse.com. The matcher's "John Tamayo" (surname) is **wrong** | Hanmades (known churned) | strong (domain) |
| 8 | Dexter Mahinay | 4 · $11,550 · Jul → Sep 25 | gmail only | **needs your name** | — |
| 9 | Siwakorn Momwong | 3 · $11,550 · Jun → Aug 25 | gmail; Xero invoice, same person | **needs your name** | — |
| 10 | Anna Webb | 8 · $11,000 · Apr → Jul 25 | gmail; Xero invoices, same person | **needs your name** | — |
| 11 | Nirav Patel | 3 · $9,900 · Apr → Jun 25 | gmail; Xero invoices, same person | **needs your name** | — |
| 12 | kranthi pasham | 1 · $8,305 · May 26 | description "Isht - 6m Scale Engine x2" | Isht | strong (description) |
| 13 | Khanh Phan | 5 · $7,012.50 · Sep → Nov 25 | gmail only | **needs your name** | — |
| 14 | Thi Kim Chi Bui | 1 · $6,490 · May 25 | @andi.melbourne + "An Di 3 Months Custom Marketing Package" | An Di | strong |
| 15 | Ronny Herrmann | 1 · $5,775 · Aug 25 | @rhe24.com + "6 Month Split Pay Angkor Cafe"; Xero "RHE24 Pty Ltd" $11,550; tracker won "Neri Roth Herrmann" (Custom, $10,500) | Angkor Cafe (= Neri Roth Herrmann's deal?) | strong for Angkor; the tracker link needs you |
| 16 | Ami Geertsma | 5 · $5,500 · Apr → Aug 25 | gmail; Xero invoices, same person | **needs your name** | — |
| 17 | John Elsley | 3 · $4,950 · Apr → Jun 25 | email @thewhistler.com.au | The Whistler | strong (domain) |
| 18 | Clement Peter | 4 · $4,537.50 · Jun → Sep 25 | email @petersfusionkitchen.com.au | Peter's Fusion Kitchen | strong (domain) |
| 19 | Jeni Arul Pragasam | 2 · $2,550 · Jul 26 | tracker won row "Jeni" / Gone Burger (Custom, $18,000); first name + amount | Gone Burger | medium |
| 20 | Manpreet Sekhon | 1 · $2,310 · Sep 25 | "Musty Custom Package $2100 6 Months Growth Pro" | Musty | strong (description) |
| 21 | Jagjeet Singh | 1 · $1,500 · Jun 26 | "Butler's Cucina Final Pay"; tracker won row "Butlers cucina" (contact Vipin) | Butlers cucina | strong (description) |
| 22 | M Shahinur Hasan | 1 · $330 · Aug 25 | "Down Payment Yo Momma Pizza" | Yo Momma Pizza | strong (description) |

## B · Bank-transfer clients (Xero paid invoices, 2026)

These are paid outside Stripe, so the measurement has never seen them. Proposed
to count as payment history **per client, once you confirm each contact → client**:

| Xero contact | Paid invoices (2026) | Note |
|---|---|---|
| Kin Fun Keng Wong | 5 × $4,708 (Jul 25 → Jul 26) | recurring; business name needed |
| Steph Wicks | 7 invoices, $1,320–$2,530 | business name needed |
| Monty's Fusions | 5 × $2,500 (Feb → Jun 26) | tracker won "Monty's Fusions Café" (Custom, $15,000): direct |
| 156 Alfred Pty Ltd | $13,750 (Apr 26) | business name needed |
| Tanny Puth | 3 × $3,355 (Jun → Aug 26) | business name needed |
| The Leopard Deli | 2 × $5,500 (Jun, Jul 26) | direct |
| Lost Sheep Cafe | $15,950 (Jul 26) | direct ($14,500 ex-GST) |
| Bar Elvina | $5,170 (Jul 26) | direct |
| Warners At The Bay | 7 × $363 weekly (Jul → Sep 26) | direct |
| Johnnies Food House | $2,000 (Sep 26) | direct |
| Walkway to Ceylon | $330 (Sep 26) | direct |
| RHE24 Pty Ltd | $11,550 (Sep 25) | = Ronny Herrmann / Angkor Cafe (row A15) |

Excluded, to avoid counting money twice: the 2025 invoices to Stripe payers
(Norvin Acabo, Anna Webb, Ami Geertsma, Adrian Sheather, Nirav Patel, John
Elsley, Clement Peter, Siwakorn Momwong, Thi Kim Chi Bui, Angela Wright). They
mirror Stripe charges. Also queried: Craig Hicks and Harry Malhi invoices
read PAID with $0 recorded paid, so there is no evidence of cash.

## What confirmation will and won't change (read before confirming)

The renewal and completion measurement needs, per client, the **package, a
term start and a contract value**. Today those come only from the tracker's won
rows, and most legacy payers above have none. Confirming an identity lets the
payment count, but a client with no package or start still sits in
"excluded, counted".

So for each confirmed client, one more line decides whether it enters the
measurement:
- **Package + start date + contract ex-GST**, from your word or the Health tab.

Custom packages (Gone Burger, Monty's, Angkor, An Di, Musty) stay outside the
retainer renewal measurement by design: a custom deal has no standard renewal
term.

## To confirm

Reply per row, for example "A2 yes · A7 yes · A1 = <business>, Growth Pro, from
2025-04-06". Each confirmation is journaled as your ruling
(`unmatched_payments.confirm`), and the measurement then re-runs and reports the
new point estimate and range.
