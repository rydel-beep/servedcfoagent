# Dashboard V2 — Decision Log

## Phase 0: Connection Report
- **GHL and Xero**: env vars only set on Railway, not locally. All development/testing for
  GHL and Xero features will work in production only. Verified locally: Sheets, Stripe MCP.
- **Stripe MCP subscriptions**: Returns 1 active, 1 past_due, 1 cancelled — but MRR is $62k.
  This counts subscription *objects*, not customer subscriptions. Known Stripe MCP limitation.
- **Stripe per-customer data**: Not available. MCP provides aggregate only. Cannot do
  per-client Stripe matching. CLAUDE.md already documents this.

## Phase 1: Client Count Reconciliation
- **Decision**: Active count = 30 (31 Active in sheet - 1 The Advocate confirmed churned)
- **Rationale**: Health tab has 31 "Active" rows. The Advocate is still marked Active in sheet
  but Rydel explicitly confirmed it's churned in prior conversation. All 11 LTC Won deals
  successfully match Health tab clients. No clients are "awaiting Stripe" anymore — all new
  signings are now in the Health tab.
- **The 32 vs 30 gap**: Rydel reported 32; sheet says 31 Active. Possible The Advocate
  was included in Rydel's count, plus The Raama (whose contract ends June 30) may still
  be counted as active despite $0 MRR this month. Our parser correctly includes both
  $0-MRR clients as active with a discrepancy flag.

## Phase 5b: Prepaid Contract Data
- **Finding**: The Health tab (GID 1407663952) now contains Start Date, End Date, Contract
  Value, Service Term, and Monthly Recognized Revenue columns. This is sufficient to build
  the renewal-watch panel without any sheet changes.

## Stage A: Accuracy Lockdown (2026-06-11)
- **Names in snapshot**: Kept roster names in snapshot JSON (the roster editor needs
  them) now that /cfo/snapshot is auth-locked. Agent CLAUDE.md rule amended: real names
  never in UNAUTHENTICATED outputs or history files. History store remains aggregate-only.
- **Consistency gate semantics**: assert_consistency() hard-fails only on internal
  arithmetic contradictions (code bugs). Cross-source disagreements stay degraded[] flags.
  On gate failure during refresh, the app keeps serving the last good snapshot.
- **Stripe MCP days bug**: MCP ignores the days param (always 30d). revenue_previous was
  silently $0 forever; now None + degraded flag. Root fix belongs in served-stripe-mcp repo.
- **$87k vs $62k**: Stripe UI "last 4 weeks" = payouts banked (NET); dashboard card =
  charges collected (GROSS). Both now shown, labeled, with window definitions.
- **Scheduled refresh**: daemon thread every 6h (REFRESH_INTERVAL_HOURS) — snapshot had
  gone 4 days stale with only startup/manual refresh.

## Stage D decisions (2026-06-11)
- **Jarvis streaming deferred**: chat.py calls Anthropic non-streaming via requests; converting
  to SSE is a risky surgery on an auth-gated endpoint under the time cap. Shipped the animated
  typing indicator + smooth autoscroll instead. Streaming is the top Stage-D+1 candidate.
- **Ad-spend slider**: does not exist in the codebase (Stage 0 inventory); the non-regression
  contract lists it but there is nothing to regress. Noted as ABSENT, not broken.
- **Window toggle**: verified purely client-side (precomputed sales.windows[]) — no refetch,
  so toggle latency is render-only (<100ms by construction).
