# CLIENT CHURN/DOWNGRADE WRITE-BACK — Phase 0 (write scope + fields + sync) — HARD STOP

**Date:** 2026-07-03 (Sydney) · **Status:** HARD STOP for Rydel's Google Sheets WRITE consent +
roster confirmation. Nothing built. This is EDITH's FIRST write capability — everything else is
read-only — so it's gated hard.

## 1. Write scope — EDITH has NO write access today
Reads happen via **public gviz CSV** (the sheet is link-shared; no OAuth, no Google credentials at
all — confirmed: zero GOOGLE_* env vars). **Writing is a brand-new auth path**, not a scope tweak.

**Required (recommended: a service account — no user-token expiry, server-side, least-privilege):**
1. In Google Cloud Console (any project): **enable the Google Sheets API**.
2. Create a **service account**; generate a **JSON key**.
3. Add the JSON key to Railway as `GOOGLE_SERVICE_ACCOUNT_JSON` (server-side, masked, never committed).
4. **Share the Finance spreadsheet** with the service account's email (…@…iam.gserviceaccount.com)
   as **Editor**.

The app then writes with scope `https://www.googleapis.com/auth/spreadsheets`, but **confined in
code to only the roster tab's Status / MRR / End-Date cells** of one matched client row (via the
Sheets API `values` range / GridRange — never arbitrary cells, never other rows).

## 2. Roster source of truth + target fields — ⚠ the brief's tab is WRONG
The brief says "Finance tab **182553893** client list." **That gid is the SALARY tab** (LAST NAME /
FIRST NAME / ROLE / DEPARTMENT / STATUS / SALARY, 19 rows) — the same mispointer caught in the
data-accuracy round. **Writing churn there would corrupt payroll.**

The real client roster is the **Health tab, gid `1407663952`** (114 rows). Its columns:

| Col | Field | Write on churn | Write on downgrade |
|---|---|---|---|
| A (0) | **Client Name** (identity) | never (match only) | never |
| B (1) | **Status** (Active/Churned) | → `Churned` | stays `Active` |
| C–E | Package / Term / Start Date | never | never |
| F (5) | **End Date** | → exit date (today or given) | never |
| G (6) | Contract Value | never | never |
| H (7) | **Monthly Recognized Revenue (MRR)** | → `0` | → new lower value |

Writes touch **B, F, H only** for the one matched row. **No churn-reason column exists** — if you
want reasons captured, add a "Churn Reason" column and I'll write it too (optional).

## 3. Write → resync — ONE direction (no mirror conflict)
```
Rydel (chat) → EDITH confirms exact row → writes the HEALTH SHEET (B/F/H of that row)
   → reads the cell back to verify the write landed → triggers sheet_mirror resync
   → Postgres mirror + dashboard (client count, MRR, churn) recompute from the updated sheet.
```
The sheet is the single source of truth; the mirror only ever **follows** it (sheet→Postgres). EDITH
**never** writes the mirror directly — that would create two writers and drift. The mirror already
reads Health by gid `1407663952`, so a resync reflects the write immediately.

## HARD STOP — needs Rydel before Phase 1
1. **Google write consent/setup** (steps in §1) — your Cloud Console action + sharing the sheet with
   the service account. Until that's done there is no write path.
2. **Confirm the roster source of truth = Health tab gid `1407663952`** (NOT 182553893/SALARY).
3. Optional: add a "Churn Reason" column if you want reasons stored.

Then Phase 1+ build autonomously: intent recognition → exact-row match → confirmation loop → write
B/F/H → read-back → resync → audit log + one-command undo.

---

## Built — dashboard override + Piolo manual-update queue (Rydel chose: no sheet write)

**Decision:** EDITH does NOT write Google Sheets. She records churn/downgrade in Postgres
(`client_overrides`); the dashboard applies it; a "For Piolo" queue lists the manual sheet edits.
No permission escalation, no HARD STOP — the risky write path is avoided entirely.

**`client_overrides.py`:** Postgres store (`client_overrides` + a TTL'd `client_override_pending`).
- **Intent:** "mark Hono Grill churned", "downgrade Naan Sense to 1500" (voice + text). Matches the
  named client against the live roster; **ambiguous → asks, never guesses**; unknown → "who exactly?".
- **Confirmation loop (non-negotiable):** echoes the exact record before recording —
  churn: "Marking Hono Grill (Active, $3,050 MRR) as CHURNED, exit 2026-07-03 — confirm?";
  downgrade: "Downgrading Naan Sense from $3,050 to $1,500, effective today, keeping Active — confirm?".
  Writes ONLY on explicit yes. Missing new-MRR on a downgrade → asks; a not-lower figure → flags.
- **Apply (count + MRR + churn):** `pull_client_health` loads the active override map once and, at the
  existing churn-skip hook, drops churned clients and lowers downgraded MRR — so active count, total/
  next MRR, and churn/retention all recompute WITHOUT touching the sheet.
- **One direction:** on confirm → mirror resync + snapshot rebuild → dashboard reflects. EDITH never
  writes the mirror or the sheet directly.
- **Piolo queue:** "what does Piolo need to update?" → the exact Health-sheet edits (Status/End-Date/
  MRR per client). Auto-**reconciles** a churn once the raw sheet shows the client non-Active.
- **Undo + audit:** "undo that" / "mark X active again" reverses the last (or a named) override +
  resyncs; "what client changes have I made?" → the audit log (active / undone / in-sheet).

Auth-gated (dashboard cookie — only Rydel). 293 tests pass (+6). Live write-path verified below.
