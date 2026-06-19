# EDITH — LIVE CASH FROM XERO (Stage 2) — STAGE 1 GATE REPORT

Run 2026-06-19 (Sydney). **STOPPED at the Stage 1 hard gate — two blockers need Rydel.**

## Stage 1 result — agent's Railway Xero OAuth is LIVE, but cannot read bank balances yet

### ✅ What works
Live read from the **deployed** context (`/debug/xero-raw`, auth-gated, key never printed):
- P&L report returned **200 OK** → `Profit & Loss · 20 May 2026 to 19 Jun 2026`.
- Token store: `/data/xero_tokens.json` (Railway volume — survives deploys; this is why Xero
  stayed connected). Refresh flow is persist-first and working.
- **So the OAuth access+refresh token is present and valid.** No expired/broken refresh.

### ⛔ Blocker 1 — OAuth scope is P&L-ONLY (cannot read bank balances)
`app.py` requests: `offline_access accounting.reports.profitandloss.read accounting.settings.read`.

`accounting.reports.profitandloss.read` is a **granular** Xero scope — it grants the **Profit &
Loss report only**. Bank account closing balances come from the **Balance Sheet** or **Bank
Summary** report, which require the broader **`accounting.reports.read`** scope. The current
token does not have it, so a balance read would 403. **Re-consent at a broader scope is
required** — a browser action only you can do.

### ⛔ Blocker 2 — the connected tenant is "THE 97 GROUP PTY LTD" (confirm it's the right org)
The agent's P&L report header is **"THE 97 GROUP PTY LTD"**, NOT "Served Marketing". Earlier in
this session the **claude.ai Xero MCP** reported Org **"Served Marketing"** and that's where the
named CommBank accounts (Transaction #2352, Saver #4041, BAS #2353) live.

- **Strong evidence it's the SAME entity:** THE 97 GROUP's P&L shows Served's exact cost lines
  (Advertising $7,342, Contractors NO GST $15,789) — these match Served Marketing's known books.
  Legal name "THE 97 GROUP PTY LTD", trading as "Served Marketing" is the most likely truth.
- **But I will not repoint CASH on an assumption.** If the agent is connected to a *different*
  Xero org than the one holding CommBank #2352/#4041, expanding scope still wouldn't surface
  those accounts. **Confirm:** is THE 97 GROUP PTY LTD the Xero org that holds CommBank
  Transaction #2352 + Saver #4041? (If yes → just need the scope. If no → connect the right org.)

---

## EXACT RESTORATION STEPS (for Rydel — gated credential action)

1. **Confirm the tenant** (Blocker 2): in Xero, is the org holding CommBank #2352 + #4041 the
   one whose legal name is **THE 97 GROUP PTY LTD**? (Reply yes/no.)
2. **Expand the scope** (Blocker 1): I add `accounting.reports.read` to `XERO_SCOPES` in `app.py`
   (keeping `offline_access` + `accounting.settings.read`) and deploy. *(I can do this on your
   go — it's a one-line code change + deploy, not a credential action.)*
3. **Re-consent (your browser, ~1 min):** after that deploy, visit
   **`https://web-production-16b16.up.railway.app/xero/connect`**, log in, pick **the org
   confirmed in step 1**, and approve. The `/xero/callback` saves a new token with the broader
   scope to `/data/xero_tokens.json`. This refresh-token keeps it alive (offline_access) so it
   won't silently expire.
4. **Verify (me):** I read the Balance Sheet / Bank Summary from the deployed context and confirm
   the **closing balances** of #2352 + #4041 come back real and positive (Stage 2A proof) before
   any repoint.

Do NOT bypass auth; the chat MCP cannot serve production. Until re-consent, **cash stays on the
labelled manual override ($140,007, confirmed 06-04) — not faked.**

---

## What happens after the gate clears (queued, not yet built)
- **Stage 2A** — prove closing-balance semantics: resolve account IDs for #2352/#4041, read the
  point-in-time closing balance (not period movement — the Stage 0 raw read came back negative =
  movement), sanity-gate vs the $140k context. STOP if anything returns negative/implausible.
- **Stage 2B** — repoint cash on hand = live Xero closing balance of #2352 + #4041 (exclude BAS
  #2353 + Amex); Stripe in-transit stays a separate labelled line; recompute runway; "as of"
  label + loud Xero-down fallback; before/after reconciliation vs $140,007.
- **Stage 3** — `SNAPSHOT_FILE=/data/snapshot_state.json` so the snapshot survives deploys.

**No code changed and no cash repointed in this step. Awaiting your confirm on Blocker 2 + go to
expand the scope.**
