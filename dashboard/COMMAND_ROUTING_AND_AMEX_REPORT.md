# COMMAND MISROUTING FIX + AMEX OWING LINE

**Date:** 2026-07-01 (Sydney)

## Phase 0 — the misrouting
"Can we afford to bump standard SMM salary to 35k PHP, then push Gabie to 40k?" → EDITH replied with
the TARGETS-COMMAND MENU ("set the LTGP:CAC target to 3.5…"). Root cause: the targets SET-trigger
(`manual_targets.py`) fired on three far-too-loose conditions:
```
set-verb (incl. bump/raise/lower)  AND  (target-word OR "to" OR "=")  AND  a digit
```
The input matched **"bump"** + **"to"** + **35** → SET path → couldn't resolve a metric → hijacked with
"Which target?". The killers: **"to" counted as a target-word** (matches almost any sentence), the trigger
**didn't require a real target metric**, and there was **no question-guard**.

## Phase 1 — tightened triggering (commands ≠ questions)
The SET command now fires ONLY when: **not phrased as a question** (`_QUESTION_RE`: can we / could we /
should we / what if / how much / afford / …), a number is present, AND either **an explicit target-noun**
(target/benchmark/ceiling/goal/floor) OR **an explicit set-verb applied to a KNOWN dashboard metric**.
Cost verbs (bump/raise/lower/push) were dropped as triggers. Verified:
- "can we afford to bump SMM to 35k, push Gabie to 40k" → NOT a command (routes to analysis) ✓
- "what if we raise Gabie to 40k", "change SMM salary to 35k", "should we change our LTGP:CAC to 3" → NOT commands ✓
- "set the LTGP:CAC target to 3.5", "gross margin benchmark to 50%", "CAC ceiling to 4000", "change LTGP:CAC to 3" → still set ✓
- "set the target to 3.5" (ambiguous but explicit) → still asks "which target?" ✓
Also: a stale pending confirmation no longer nags — a fresh question supersedes it.

## Phase 2 — affordability routing
With the misrouting gone, affordability questions reach analysis (the model) with burn ($32.7k), runway
(5.3mo), and cash in context. NOTE (honest gap): per-person salaries live in the Finance SALARY tab
(Gabie De Leon etc.) but the snapshot's `team_model.roles` carries roles WITHOUT amounts — so the model
can give a directional affordability read but not an exact SMM/Gabie delta until per-person salaries are
surfaced. Flagged as a follow-up (surface SALARY-tab amounts or a deterministic salary-impact handler).

## Phase 3 — Amex owing (liability, separate from cash)
Amex is a credit card (a liability), correctly EXCLUDED from cash on hand. It's shown in Xero's Bank
Summary with a NEGATIVE balance (−$18,152.80) = money owed. `xero_pull._extract_amex_owing` reads it from
the SAME Bank Summary (same single-use refresh) → `snapshot.xero.amex_owing = {owing, as_of, account}`.
Surfaced as: a **liability line on the dashboard** ("Amex owing: −$X, as of <date>, not in cash") and a
deterministic voice answer (`liabilities_view.handle_amex_command`: "what do we owe on Amex?" → the figure
verbatim). Never netted into cash, never double-counted; Xero-fail → "can't read the Amex balance". 283
tests pass (+8 this round).
