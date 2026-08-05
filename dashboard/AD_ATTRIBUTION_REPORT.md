# EDITH — Ad Creative Attribution Engine

## PHASE 3 — THE HORMOZI VERDICT LAYER (2026-08-05) — LIVE (Phase 4 held by Rydel)

`attribution_verdicts.py` (pure, DECISIONS #113), applied inside the engine so every
surface reads the same verdicts:

- **Ranking metric:** LTGP:CAC vs the registry floor (`manual_targets.ltgp_cac_target`,
  3.0x). Bands: DOUBLE DOWN at ≥ floor×1.1 with ≥3 closes; borderline ×0.9–×1.1 holds;
  KILL below ×0.9 **only at ≥30 attributed leads** — closes alone never kill (Rydel's
  rule). Every verdict driver carries the actual figures.
- **Zero-close discipline:** a 30-lead zero-close creative KILLs only when its leads also
  SET below the account rate (lead quality is the creative's output); if its leads set
  fine, the verdict names the **sales handoff** instead — the stage, not the creative.
- **Stage diagnostics:** per-creative cohort rates (lead→qualified→set→show→close) vs
  account baselines; denominators <3 are shown, never judged; the worst stage is named in
  the verdict so Romano fixes the right thing.
- **Constraint check:** if ALL sufficient-n creatives clear the floor, the layer says
  plainly "creative selection isn't the constraint; volume/capacity is" with the capacity
  engine's worst-department load attached; with no sufficient-n creatives it says that
  honestly too. Nothing auto-pauses; no Meta write exists (test-enforced).
- **Salience:** a creative newly crossing to DOUBLE DOWN or KILL at sufficient n
  announces once in the greeting (kv crossings → salience, watermarked).

### Phase 4 prep shipped CFO-side (section itself HELD until the timeline repo frees)

- `GET /bridge/attribution?days=` — the endpoint the Timeline AD TRACKING section will
  proxy; owner tokens work today.
- **media_buyer role — designed, SHIPS DISABLED:** `EDITH_BRIDGE_MEDIA_BUYERS` env
  (default empty). A media_buyer token reaches exactly ONE route (`/bridge/attribution`);
  ping, email, send — every owner surface — 403s it server-side (the sales-role pattern,
  test-enforced). Flip-on for Romano = set the env var; nothing else changes.
- **Piolo's queue wired:** the engine publishes duplicate-won-row flags to kv → the
  action feed (data_quality) → `collab.queue()`. The Nirosha item appears there with
  "fix the row at source" and SELF-RETIRES once the tracker is clean (the engine
  overwrites the list each compute; the explicit-duplicates reconciliation term then
  reads 0).

Suite: **513 tests green** (14 verdict tests + 4 role-scoping tests added).

## PHASES 1-2 — THE JOIN + THE PER-CREATIVE ENGINE (2026-08-04) — LIVE

Rydel's Phase-0 confirmations are encoded in DECISIONS #111. Modules (all read-only against
external systems; ads_read only, test-enforced — no Meta write call exists):

- **meta_entities.py** — ad entity map (ALL effective statuses incl. ARCHIVED — the default
  /ads listing was proven incomplete in Phase 0), direct-id lookups with negative caching,
  insights name→id alias recovery (kv `attr:ad_aliases`, learned like payment aliases),
  per-ad daily spend store (level=ad insights, meta_spend's retroactive-backfill discipline),
  and `reconcile_spend()` proving Σ(per-ad) against the canonical account engine.
- **attribution_join.py** — full-CRM contact sweep (list endpoint carries `attributions`;
  ~36 GETs, TTL 6h) into the auth-gated `attr_contacts` table; pure classification:
  id-first ad refs (utmAdId → id-style utm_content → name), tiers ad / ig_dm / other / none;
  `resolve_ref()` → creative identity keyed by NORMALIZED AD NAME (survives the 114
  duplicate names; ambiguous names group at creative level with member ad ids listed,
  adset/campaign never guessed).
- **attribution_engine.py** — tracker-row-centric stitch (the lead universe IS the clean
  tracker, so lead totals reconcile structurally): qualified = setter outcome ≠ DQ; funnel
  cohort by Input Date; money metrics close-date basis (unit_economics parity); the dedupe
  rule for duplicate won rows (counted once, flagged, explicit term in the closes
  reconciliation); IG-DM channel row + always-visible Unattributed row; IG non-lead
  inquiries bucket (excluded from lead math, visible, borderline flagged); min-n gates
  (KILL needs 30 leads, scale fires on 3 closes, else "watch — insufficient data (n=…)");
  validation flags (qualified-vs-inquiry-signals, DQ-but-progressed, unmatched leads) —
  flag only, never reclassify. `/cfo/attribution?days=` (same owner gate as the snapshot).

### Live verification (production data, 2026-08-04)

| Window | Leads | Attributed | Closes | Cash | Spend | Reconciliation |
|---|---|---|---|---|---|---|
| 30d (Jul 6 → Aug 4) | 78 | 67 (**85.9%**) | 6 | $41,635 | $10,363.77 | **ALL OK, 0.0% drift** |
| 60d (Jun 6 → Aug 4) | 164 | 148 (**90.2%**) | 10 | $59,945 | $18,923.18 | **ALL OK, 0.0% drift** |

- All four identities exact both windows: leads engine=canonical, closes (with the explicit
  duplicates term), cash to the cent, Σ per-creative spend = account engine total.
- The dedupe rule caught the real Nirosha duplicate won row live (same contract value,
  counted once, flagged "fix at source"); the two John Tamayo rows share a close date and
  dedupe likewise. Ads with spend but zero leads appear in the table (the kill signal is
  visible, e.g. B009_A03 at $317.52 / 0 leads in 30d).
- IG non-lead inquiries: 112 (30d) / 224 (60d) — visible, excluded from lead math.
- Every creative currently gates "watch — insufficient data" at 30d (top spender
  B008_A04: 17 leads, 1 close) — the min-n discipline working as confirmed: no verdict
  until 30 leads or 3 closes. At 60d, B004_A04 (2 closes, $24,255 cash, ROAS-c 46×) is the
  closest to a scale-gate creative.
- LTGP:CAC omits (with an explicit degraded entry) when gross margin is unavailable —
  populated on the deployed service where the persisted snapshot carries
  xero.gross_margin_pct.
- Suite: 478 tests green including 19 new adversarial attribution tests.

## PHASE 0 — THE ATTRIBUTION TRUTH AUDIT (2026-08-04) — AWAITING RYDEL'S CONFIRMATIONS

Read-only audit. Sources: GHL contacts API (all 3,527 contacts, full sweep — not a sample),
GHL opportunities search (sales pipeline, 1,355 opps), Meta Graph `/ads` + direct id lookups +
2025 insights (act_1071149830652711, ads_read only), Lead-to-Cash tracker (live CSV read),
existing Stripe reconcile engine. Zero writes anywhere. Raw dumps (PII) kept out of the repo.

### 1 · The attribution distribution (all 3,527 contacts)

| Class | Count | % | Recent 90d | Older |
|---|---|---|---|---|
| **AD-level** (utmAdId or utm_content) | **1,469** | **41.7%** | 217 | 1,252 |
| CAMPAIGN-only | 0 | 0% | 0 | 0 |
| SOURCE-only (medium/referrer, no ids) | 1,791 | 50.8% | 292 | 1,499 |
| NONE (manual/import) | 267 | 7.6% | 67 | 200 |

- `csv_import` accounts for 1,214 contacts (34% of the CRM) — bulk-imported, never attributable.
  **Excluding imports, 63.5% of organically-arrived contacts carry ad-level identity.**
- The money view is far better than the raw %: **57 of 67 tracker WON deals (85%) are
  ad-attributed**; 88% of open sales-pipeline opps sit on attributed contacts.
- fbclid present but not ad-resolvable: 37 contacts (click identity exists; no retroactive ad
  link possible — stays honest-unattributed).

### 2 · Resolution test (contact → exact Meta creative), id-first

Of the 1,469 ad-level contacts:

| Resolution | Count |
|---|---|
| Exact **ad ID** (utmAdId, or id-style utm_content) | **960** |
| Ad NAME, unique match | 96 |
| Ad NAME, ambiguous (name duplicated across ads) | 349 |
| Unresolved (deleted/renamed old ads) | 64 |

= **72% of ad-level contacts resolve cleanly today; 96% resolve at least to a creative name.**

Worked examples (10 id-based, verified live): e.g. contact `ton…` → utmAdId
`120249363416150167` → ad "C G3 Q326 Served Graphics July 2026 2nd Batch - Graphic 3"
[Served 2026 Retargetting Campaign]; contact `mne…` → `120249259301090167` → "G1 Florida
Served Marketing Graphic ADS - USA Batch 01" [Served 2026 USA Campaign]. Full set in the
Phase 0 session output.

Pitfalls proven, with mitigations for Phase 1:
- **114 of 338 ad names are duplicated** across campaigns (same creative re-launched in TOF /
  Retargeting / USA). Name-only resolution mis-lands 970 contacts; id-first cuts that to 349.
- The default `/ads` listing is incomplete (returned 507; several referenced ads missing but
  alive) — Phase 1 join must include archived/direct-id lookups, not trust one listing.
- Deleted/old ads are recoverable via **insights by ad name** ("Retargeting NEW VSL" →
  ad_id 120227225746080167, $4,821.74 spend 2025) — the alias-map learns these.

### 3 · Capture-gap diagnosis (per channel)

| Channel | Volume (recent 90d) | Ad identity? | Diagnosis |
|---|---|---|---|
| FB lead forms (`medium=facebook`) | 212 | ✅ **utmAdId + utmCampaignId stamped by GHL** | WORKING today. Names + real ids land on every lead-form contact. |
| Instagram DM (`medium=instagram`) | **248** | ❌ none | **The biggest live gap** — ~43% of recent leads. IG-sourced (DM/comment) contacts carry only the IG account id. If these originate from click-to-DM ads, the ad identity is not captured. |
| Website (surveys/forms on servedmarketing.com.au, bookingsplaybook, etc.) | ~20 | ❌ fbc/fbp only, no UTMs | **0 of 451 ad link URLs contain any utm_ parameter; all 17 ACTIVE ads have empty url_tags.** The pages record the URL faithfully — the ads simply don't send UTMs. Historical contacts prove the id-template existed once (utm_content=ad id, utm_term=adset id) and was dropped. |
| CSV import | ~1 | ❌ | Honest floor — explicit Unattributed bucket. |
| Manual/setter/calendar/conversation | small | ❌ mostly | Honest floor. |

### 4 · Forward-capture checklist (ROMANO — can start immediately)

1. **Apply URL parameters to ALL active + future ads** (Ads Manager → ad level → Website URL →
   "URL parameters"; paste exactly):
   `utm_source=facebook&utm_medium=paid&utm_campaign={{campaign.id}}&utm_content={{ad.id}}&utm_term={{adset.id}}`
   IDs, not names — 114 duplicate names and renames make names unreliable; ids never break.
   Today zero active ads carry any URL params, so every website-click lead lands unattributed.
2. **Lead-form ads: no change needed** — the GHL⇄FB integration already stamps utmAdId +
   utmCampaignId. Keep the integration connected; don't "clean up" those fields.
3. **Instagram click-to-DM (decision needed):** 248 recent leads have no ad identity. Options:
   (a) shift IG spend toward lead-form / site-click objectives where sensible, (b) investigate
   GHL's IG integration for ad-referral payload capture, (c) accept IG-DM as an honestly
   unattributed channel. Rydel/Romano call.
4. **Landing pages:** GHL-hosted pages inherit UTMs once ads carry them. For pages on
   servedmarketing.com.au, verify the embedded survey/form persists query params — tested
   end-to-end in the Phase 5 forward proof.
5. **No GHL stamping workflow needed for v1** — GHL already persists first- AND last-touch
   attribution objects per contact.

### 5 · Stitch coverage (per link)

- **Contact → opportunity:** 1,355 sales-pipeline opps; attributed contacts: open 1,149/1,303
  (88%), won 17/20, lost 25/31. All opps carry `lastStageChangeAt`, but GHL exposes no full
  stage history → **set/show/close DATING comes from the tracker** (Set Date / Show Status /
  Close Date columns), which is the funnel source of truth already.
- **Tracker WON → GHL contact:** 67 won rows → 64 matched (63 by email, 1 by name), 3 unmatched
  ("the leopard…", "bunni beez…", "phu m truong…"). Note: 2 duplicate won rows exist
  (john tamayo, nirosha dush…) — dedupe rule needed in Phase 2 reconciliation.
- **WON attribution: 57/67 ad-attributed, 7 source-only (survey/conversation), 0 blank.**
- **Tracker → Stripe cash:** existing reconcile engine healthy — 29 charges (30d) checked,
  27 auto-recognised, 2 needs-review, 0 paid-but-missing-from-tracker.

### HARD STOP — decisions Rydel must confirm before Phase 1

1. **First-touch default** for creative credit (last-touch shown alongside, labelled)?
2. **"Qualified lead" definition** — which marker = qualified? (Candidates: setter Call
   Outcome ≠ DQ, or a specific pipeline stage.)
3. **Minimum-n gates** — proposed: no verdict under 30 attributed leads or 3 closes
   (whichever first); "watch" below that.
4. Romano receives the checklist above (§4) — those fixes are independent of the build.
