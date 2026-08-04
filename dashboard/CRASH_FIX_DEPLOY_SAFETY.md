# Crash Fix + Deploy-Safety Build — 2026-08-04

## The incident

Deploy `750666c2` (the Phase C send-chain increment, commit `c54360e`, ~17:20 AEST) carried
a SyntaxError in `dashboard/bridge.py:229` — double-escaped quotes (JSON-style `\"` inside
a double-quoted Python string). `app.py` imports the bridge at module level (line 45), so
the whole service failed boot. **Fail-closed held:** no sends were possible while down,
Postgres is a separate service and stayed healthy, no data lost.

**Why the gate didn't run:** a syntax error fails pytest COLLECTION — the suite cannot have
run green against that tree. The mid-build increment was deployed without it. That process
gap (mid-build increments deployable with zero structural check) is what this build closes.

## Step 1 — the fix + the proof of the tree

**The one-line fix was already applied by the email-completion session itself** (hotfix
`6b76314`, 17:24 — line 229 now reads `'Send %r to %d recipients now?' % (...)`, valid
syntax). Per the isolation rule this session touched NOTHING in bridge.py — verified the
fix, then proved the tree:

- `python -m compileall -q .` → exit 0 (clean).
- Sibling-pattern sweep (`\\"` inside Python literals, all recently-changed files) → zero
  instances. The one bad line was the only one.
- `python -c "import app"` → exit 0.
- Full suite → **495 passed** (collection works; includes the email session's new tests
  and the 19 attribution tests).
- Live verification (production, in order): `/health` 200 (snapshot 0.9 min old) ·
  `/dashboard` serves (308 → login) · `/cfo/snapshot` + `/cfo/attribution` 401-gated ·
  bridge answers a real owner exchange with a minted HMAC token — `/bridge/ping` 200,
  `/bridge/greeting` 200 (salience events fire, incl. a live CPL alert),
  `/bridge/email/list` 200 (board renders: 17 DRAFTING / 14 READY / 1 STAGED_IN_GHL).
- Downtime: ~4–6 minutes (crash ~17:20 → hotfix committed 17:24, live minutes later).

**Email-completion session resume point:** NONE — it ran to completion after its own
hotfix. Phase C send chain is code-complete and adversarially verified to the empty-list
boundary (see `EMAIL_SYSTEM_STATE.md` as-built section). Outstanding items are human
steps, not code: (1) Tristan creates the `newsletter` tag; (2) tag one internal contact
`edith-test-internal`, then run the one test-segment send from the board; (3) paste the
Winback SOP. Nothing to resume, nothing double-done; no send-chain logic was touched by
this session.

## Step 2 — incident note

Logged to the production incident log (kv `incidents:log`, 17:38) + DECISIONS #112.
Pattern named without blame theatre: mid-build increments were deployable without any
structural check.

## Step 3 — the build gate (structure, not policy)

Build system inspected: **Nixpacks** (Procfile + runtime.txt; no Dockerfile). Added
`railway.json`:

```json
"build": {"builder": "NIXPACKS",
          "buildCommand": "python -m compileall -q . && python -c \"import app\""}
```

Nixpacks runs this after the install phase (deps present). A syntax or import-time error
now **fails the BUILD** → Railway never switches traffic → the previous deployment keeps
serving.

**Demonstrated on a scratch worktree (never deployed, discarded after):** injected the
exact incident escape pattern into bridge.py → `compileall` exit 1 (reproducing the
production error verbatim), `import app` exit 1 — either fails the build. Clean tree →
exit 0. 

## Step 4 — Railway healthcheck

Not previously configured (which is why a crashed boot could replace production).
**This repo now sets it as config-as-code** in `railway.json`:
`"deploy": {"healthcheckPath": "/health", "healthcheckTimeout": 300}` — a deploy whose
worker fails boot is marked FAILED and the previous deployment keeps serving.

**For Rydel (2 minutes, the timeline service):** Railway → project **triumphant-vibrancy**
→ the timeline service → Settings → Deploy → **Healthcheck Path: set to `/health`**
(timeout ~300s default is fine) → save. (Or add the same `railway.json` deploy block in
the timelinedashboard repo next session there.) The CFOagent service needs no dashboard
step — railway.json carries it from this deploy onward.

Belt AND braces: the build gate stops un-compilable code before an image exists; the
healthcheck stops anything that builds but can't boot/serve from replacing the live
deployment.

## Step 5 — boot logging + the rule

- **boot_banner.py** (new): `pre_import()` lines before each risky module-level import —
  a boot-crashing import's last log lines always name the module; `emit()` prints the
  structured banner: commit sha (RAILWAY_GIT_COMMIT_SHA), Sydney boot time, python
  version, modules_ok, config presence (env var **NAMES ONLY — never values**), DB
  connectivity, worker pid.
- **/health enriched**: now carries `{commit, booted_at, modules_ok}` alongside the
  existing subsystem triage — "what version is live" at a glance, readable by the
  automation-health registry.
- **Uncaught-exception logging**: `@app.errorhandler(Exception)` logs structured
  (method, route, error class, traceback) before returning a JSON 500; HTTP errors
  (404/405) pass through untouched. No silent worker deaths.
- **The rule encoded** in CLAUDE.md + DECISIONS #112 (this repo): *No deploy without
  compileall clean + import smoke + full suite green. The build gate enforces the first
  two structurally; the suite is the agent's non-negotiable pre-push step, including
  mid-build increments. Incremental deploys are still deploys.* The timelinedashboard
  repo's CLAUDE.md/DECISIONS get the same paragraph next session in that repo (not
  reachable from this session's filesystem scope — flagged in session notes).

## Isolation proof

`git diff` for this session's commits touches ONLY: `railway.json` (new), `boot_banner.py`
(new), `app.py` (additive: pre_import/module_ok lines, banner emit, errorhandler, /health
keys), `CLAUDE.md` + `DECISIONS.md` + this report + session notes. **Zero lines of
bridge.py, email_pipeline.py, ghl_email.py, or any send-chain logic changed.** The
one-line fix itself belongs to the email session's hotfix `6b76314`, already deployed.
