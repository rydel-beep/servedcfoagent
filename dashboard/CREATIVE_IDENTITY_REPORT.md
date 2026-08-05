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
