#!/usr/bin/env python3
"""ship.py — THE DEPLOY PIPELINE (#171, Phase 0). One command, no human in the loop.

    python3 scripts/ship.py            # test → push → wait → gate → (revert on fail)
    python3 scripts/ship.py --dry-run  # everything up to the push, no push
    python3 scripts/ship.py --gates-only   # skip test+push: gate what is live now

The steps, in order — a failure at any step STOPS the pipeline and says why
in plain English:

  1 PREFLIGHT   the working tree has nothing uncommitted that would ship
                untested; `python -m compileall`; `python -c "import app"`;
                the FULL test suite (DECISIONS #112 — never partial).
  2 PUSH        `git push origin main` (exactly that).
  3 WAIT        poll production /health until it reports HEAD's commit
                (Railway's build gate keeps the previous build serving while
                the new one builds; a build failure shows as a timeout here).
  4 GATE        scripts/render_gate.py + scripts/behaviour_gate.py against
                production, logged in as the READ-ONLY GATE ACCOUNT
                (scripts/gate_creds.py — never the owner's password once
                GATE_BOT_PASSWORD exists).
  5 REVERT      if either gate fails: `git revert --no-edit HEAD`, push the
                revert, wait for it to serve, and report. The commit stays in
                history; production goes back to the last gated code.

Every run writes dashboard/evidence/ship-<commit>/report.json + report.md
(plain English). The password is never read by this script: the gate
scripts resolve it themselves and never print it.

Exit codes: 0 shipped+gated · 2 preflight refused · 3 push failed ·
4 deploy never served · 5 gates failed and the revert is live ·
6 gates failed AND the revert did not serve (loud).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
PY = sys.executable
DEPLOY_WAIT_S = int(os.environ.get("SHIP_DEPLOY_WAIT_S", "900"))
POLL_S = 15
WARM_WAIT_S = int(os.environ.get("SHIP_WARM_WAIT_S", "600"))

REPORT: dict = {"base": BASE, "steps": [], "ok": False}


def step(name: str, ok: bool, detail: str = "", **extra) -> None:
    REPORT["steps"].append({"step": name, "ok": ok, "detail": detail, **extra})
    print(("  ✓ " if ok else "  ✗ ") + name + (f" — {detail}" if detail else ""))


def sh(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def head() -> str:
    return sh(["git", "rev-parse", "HEAD"])[1].strip()


def live_commit() -> str | None:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
            return (json.loads(r.read()).get("commit") or "")[:12] or None
    except Exception:  # noqa: BLE001
        return None


def write_report(commit: str) -> str:
    evd = os.path.join(ROOT, "dashboard", "evidence", f"ship-{commit[:12]}")
    os.makedirs(evd, exist_ok=True)
    REPORT["commit"] = commit
    REPORT["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(evd, "report.json"), "w") as f:
        json.dump(REPORT, f, indent=1)
    lines = [f"# Ship report — {commit[:12]}", "", REPORT.get("summary", ""), ""]
    for s in REPORT["steps"]:
        lines.append(f"- {'PASS' if s['ok'] else 'FAIL'} · {s['step']}"
                     + (f" — {s['detail']}" if s.get("detail") else ""))
    with open(os.path.join(evd, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return evd


# ── 1 · preflight ───────────────────────────────────────────────────────────

def preflight(skip_tests: bool = False) -> bool:
    code, out = sh(["git", "status", "--porcelain"])
    # the pipeline's and the gates' own evidence folders never count as
    # "uncommitted work" — they are written by every run, by design
    dirty = [ln for ln in out.splitlines()
             if ln.strip() and not ln.endswith("SENTINEL_QUEUE.md")
             and not ln.endswith(".DS_Store")
             and "dashboard/evidence/" not in ln]
    if dirty:
        step("working tree clean", False,
             f"{len(dirty)} uncommitted change(s) would not ship — commit or stash them first",
             files=dirty[:10])
        return False
    step("working tree clean", True)

    code, out = sh([PY, "-m", "compileall", "-q", "."])
    if code != 0:
        step("every file compiles", False, out.strip()[-400:])
        return False
    step("every file compiles", True)

    code, out = sh([PY, "-c", "import app"], timeout=300)
    if code != 0:
        step("the app imports", False, out.strip()[-400:])
        return False
    step("the app imports", True)

    if skip_tests:
        step("full test suite", True, "SKIPPED by flag — not a gated ship")
        return True
    t0 = time.time()
    code, out = sh([PY, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
                   timeout=3600)
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    if code != 0:
        step("full test suite", False, tail[:200], seconds=round(time.time() - t0))
        return False
    step("full test suite", True, tail[:200], seconds=round(time.time() - t0))
    return True


# ── 2 · push ────────────────────────────────────────────────────────────────

def push() -> bool:
    code, out = sh(["git", "push", "origin", "main"], timeout=300)
    if code != 0:
        step("git push origin main", False, out.strip()[-300:])
        return False
    step("git push origin main", True)
    return True


# ── 3 · wait for the deploy ─────────────────────────────────────────────────

def wait_for(commit: str) -> bool:
    t0 = time.time()
    last = None
    while time.time() - t0 < DEPLOY_WAIT_S:
        lc = live_commit()
        if lc and commit.startswith(lc):
            step("production serves the pushed commit", True,
                 f"after {round(time.time() - t0)}s", live=lc)
            return True
        last = lc
        time.sleep(POLL_S)
    step("production serves the pushed commit", False,
         f"still serving {last or 'unknown'} after {DEPLOY_WAIT_S}s — the Railway "
         "build may have failed (its build gate keeps the old build serving)", live=last)
    return False


def wait_warm() -> None:
    """A fresh boot rebuilds the snapshot and warms every engine cache in the
    SAME workers that serve pages. Gating mid-warm measured that boot work,
    not the code (both 3 Oct reverts were 30 s page timeouts with the
    snapshot 'missing'). Wait — bounded — until /health shows a snapshot,
    then let the 45 s exec-top warm finish. The gates are unchanged; they
    still decide."""
    t0 = time.time()
    while time.time() - t0 < WARM_WAIT_S:
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=20) as r:
                snap = (json.loads(r.read()).get("subsystems") or {}).get("snapshot")
        except Exception:  # noqa: BLE001
            snap = None
        if isinstance(snap, dict) and snap.get("present"):
            time.sleep(60)
            step("production warm (snapshot present)", True,
                 f"after {round(time.time() - t0)}s")
            return
        time.sleep(POLL_S)
    step("production warm (snapshot present)", True,
         f"not warm after {WARM_WAIT_S}s — gating anyway (informational)")


# ── 4 · gates ───────────────────────────────────────────────────────────────

def _gate_prefix() -> list[str]:
    """No local gate credential → run ONLY the gate processes under
    `railway run`, so the service's own env supplies the login (interim,
    until GATE_BOT_PASSWORD exists). The test suite never runs that way."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import gate_creds
    if gate_creds.resolve()[2] != "none":
        return []
    import shutil
    if shutil.which("railway"):
        step("gate credential", True, "none locally — the gates run under `railway run` "
             "(interim; set GATE_BOT_PASSWORD + .gate_password to retire this)")
        return ["railway", "run"]
    step("gate credential", False, gate_creds.describe("none"))
    return []


def run_gates() -> bool:
    env = dict(os.environ, GATE_BASE=BASE, GATE_HOLD=os.environ.get("GATE_HOLD", "0"),
               BEHAVIOUR_PASSES=os.environ.get("BEHAVIOUR_PASSES", "2"))
    prefix = _gate_prefix()
    ok_all = True
    for script, label in (("render_gate.py", "render gate"),
                          ("behaviour_gate.py", "behaviour gate")):
        t0 = time.time()
        r = subprocess.run(prefix + [PY, os.path.join(ROOT, "scripts", script)], cwd=ROOT,
                           capture_output=True, text=True, env=env, timeout=1800)
        out = (r.stdout + r.stderr)
        fails = [ln for ln in out.splitlines() if "FAIL" in ln][:8]
        mode = next((ln for ln in out.splitlines() if "logging in as" in ln), "")
        ok = r.returncode == 0
        ok_all = ok_all and ok
        step(label, ok, (mode.split("logging in as ")[-1] if mode else "")
             + ("" if ok else (" · " + "; ".join(fails) if fails else
                               f" · exit {r.returncode}: {out.strip()[-300:]}")),
             seconds=round(time.time() - t0), exit=r.returncode)
    return ok_all


# ── 5 · revert ──────────────────────────────────────────────────────────────

def revert(bad_commit: str) -> bool:
    code, out = sh(["git", "revert", "--no-edit", bad_commit])
    if code != 0:
        step("revert committed", False, out.strip()[-300:])
        return False
    step("revert committed", True, f"reverts {bad_commit[:12]}")
    if not push():
        return False
    return wait_for(head())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="stop before the push")
    ap.add_argument("--gates-only", action="store_true", help="gate what is live now")
    ap.add_argument("--skip-tests", action="store_true",
                    help="UNGATED — never for a real ship; for pipeline drills only")
    a = ap.parse_args()
    commit = head()
    print(f"ship: HEAD {commit[:12]} → {BASE}")

    if a.gates_only:
        lc = live_commit()
        step("production reachable", bool(lc), f"serving {lc}" if lc else "no /health")
        ok = run_gates()
        REPORT["ok"] = ok
        REPORT["summary"] = ("Production passed both gates." if ok else
                             "Production FAILED a gate — see the steps; nothing was pushed or reverted.")
        print(write_report(lc or commit))
        return 0 if ok else 5

    if not preflight(skip_tests=a.skip_tests):
        REPORT["summary"] = "Refused before the push: the change did not pass preflight. Production is unchanged."
        print(write_report(commit))
        return 2
    if a.dry_run:
        REPORT["ok"] = True
        REPORT["summary"] = "Dry run: preflight passed; nothing was pushed."
        print(write_report(commit))
        return 0
    if not push():
        REPORT["summary"] = "The push failed. Production is unchanged."
        print(write_report(commit))
        return 3
    if not wait_for(commit):
        REPORT["summary"] = ("Pushed, but production never served the new commit — most likely the "
                             "Railway build failed and the previous build is still serving.")
        print(write_report(commit))
        return 4
    wait_warm()
    if run_gates():
        REPORT["ok"] = True
        REPORT["summary"] = f"Shipped and gated: production is running {commit[:12]}."
        print(write_report(commit))
        return 0
    # gates failed → revert
    print("ship: a gate failed — reverting")
    reverted = revert(commit)
    if reverted:
        REPORT["summary"] = (f"{commit[:12]} failed a post-deploy gate and was reverted; "
                             f"production is back on the previous code ({head()[:12]} = the revert).")
        print(write_report(commit))
        return 5
    REPORT["summary"] = (f"{commit[:12]} failed a gate AND the revert did not serve — "
                         "production needs a human look now.")
    print(write_report(commit))
    return 6


if __name__ == "__main__":
    sys.exit(main())
