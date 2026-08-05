# Creative Identity Forensics + the Join Contract

## PHASE 0 — THE AMBIGUITY REPORT (2026-08-05) — AWAITING RYDEL'S KEYING POLICY

Read-only forensics over the FULL entity map (715 ads incl. archived/extras), lifetime
spend (insights sweeps, $83,807 total), the contact store, and the live engine.
Full machine-readable register: scratchpad/dup_register.json; top entries below.

### 1 · The duplicate-name register — THE HEADLINE
**199 names are used by more than one ad id — 504 member ads** (the earlier "114" came
from the incomplete default listing; archived members widen it). The pattern: the same
creative re-launched across TOF / Retargeting / LP / USA campaigns. Top rows by 30d spend:

| Name | Members | The merge (30d) |
|---|---|---|
| B008_A04_Brash…Bluebells_v1 | TOF + Retargeting | $1,505/17 contacts/1 close (TOF) blended with $234/2/0 (RT) |
| C G3 Q326 Graphics…Graphic 3 | TOF + Retargeting | $470/4 (TOF) + $171/1 (RT) |
| B010_A06_Comparison…v2 | TOF + Retargeting | $455/3 + $113/0 |
| G2 News Article DEC 2025 | 3 ads, ALL USA campaign | three distinct ads, one row |
| B001_A05_PainPoint_William… | **7 members** across USA/LP/RT/TOF | today's row shows $292/1 lead; the TOF member holds 26 contacts + 1 close ($1,623 life) — invisible |
| 'vid 5' | 3 members | one member: 63 contacts + 1 close; two: zero — the row can't say which |

### 2 · Merge impact (30d): **7 displayed rows are merges.** No verdict flips at current
n (all watch), but the TOF-vs-Retargeting blend polls different audiences into one
provisional read — exactly the distortion Rydel is feeling; at verdict-n it WOULD
mis-verdict (per-campaign economics differ systematically).

### 3 · Resolution-path census (30d window leads)
| Path | Count | Share of attributed |
|---|---|---|
| exact ad id (utmAdId / id-utm) | 65 | **94%** |
| unique name | 2 | 3% |
| **non-unique name (currently MERGED into the name row)** | 2 | 3% |
| unattributed | 11 leads | — |

**The precision already exists** — 94% of current leads carry the exact ad id. The wrong
numbers come from the GROUPING: the engine keys rows by normalized NAME, so exact-id
attributions from different campaigns merge. All-time, 379 name-resolved contacts sit on
duplicated names (the pre-utmAdId era) — those are genuinely ambiguous and today they
silently merge into name rows implying certainty.

### 4 · Naming convention: 112 ads follow B###_A##_ (batch+angle parseable), 44 are
G#-style graphics, 559 freeform — the batch ladder level stays name-prefix based;
an angle level is honest only for the B### population.

### 5 · Current keying: `meta_entities.norm_name()` (lowercase, whitespace-collapse) on
the AD NAME; engine `creative_key` = that name (or `id:<ad_id>`); rows GROUP BY it.

### THE OPTIONS (hard stop)
(a) **AD-ID level** — every ad id its own row; labels "Name [Campaign]"; max precision.
(b) **NAME-GROUPED** — current behaviour (campaign-blended).
(c) **HYBRID (recommended)** — AD-ID is the base key and the truth; name / batch /
campaign are LADDER LEVELS (see the same creative across campaigns deliberately, split
it deliberately — neither view lies). Ambiguous-name contacts quarantined in every mode.
Plus: label format, and archived/deleted member display (recommend shown, marked — their
spend and leads are real history).

## RYDEL'S RULINGS + THE BUILD (2026-08-05)
HYBRID keying · "Name [Campaign]" labels · archived/deleted shown marked. Implemented:
resolve_ref re-keyed (ad-id truth, campaign-disambiguated labels, history marks); the
__ambiguous__ quarantine row (candidates in the drill — never assigned); the ladder's
NAME level (deliberate cross-campaign grouping); identity_health (census + per-hop
measured rates + exact-id degradation flag → salience) on the /ads hygiene strip;
JOIN_CONTRACT.md; EDITH: tracking-accuracy + shared-name answers (fabricated refused).

## LIVE PROOF (production data)
- B008_A04: ONE merged row → TWO rows: [TOF] 15 leads/$1,505/1 close TRENDING STRONG vs
  [Retargeting] 2 leads/$234 EARLY. Name level regroups: 17 leads/$1,739/2 members —
  split↔group reconciles exactly.
- Ambiguous quarantine: 2 leads (the census's 2 non-unique-name leads — no longer merged
  into certain-looking rows). History members render marked ("Kin May Testimonial - Copy
  (archived)").
- Identity strip live: 97% exact-id · hop2 97.5% (email 96.2%) · trailing 90d 98.3%.
- JOURNALED RE-STATEMENT: 30d attributed 69 → 67 (2 → quarantine); attribution rate
  86.2% → 83.8% — the delta is honesty (attributed now means CERTAIN), not lost data.
- EDITH: accuracy answer verbatim; "which ads share the name B008_A04…" lists both
  members with campaigns/status; "Zebulon Mega VSL" → refused.
- Suite 579 green (identity tests: quarantine-never-assigned, name-level sums, census +
  degradation). Screenshot: claude-chrome-screenshots-UO7oRw/…-4.jpg (the board with
  the identity strip + hygiene items).

FORWARD TRAJECTORY: lead-form utmAdId keeps exact-id ≈ 94-98%; ambiguity is confined to
the pre-id era (379 all-time contacts) and shrinks to zero for new leads.
