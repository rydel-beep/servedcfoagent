"""replay_witnessed_thread.py — THE WITNESSED 24 SEP THREAD, RE-RUN LIVE (#168).

The two questions verbatim, then the verification drills, through the real
dock endpoint with a real login. The transcript is the report's evidence.

Run under `railway run` so RYDEL_PASSWORD comes from the environment:
  railway run python3 scripts/replay_witnessed_thread.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import requests

BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")

THREAD = [
    "are you meaning we are at negative net profit right now? From Sept 1 to 24?",
    "No I just want the Sept 1 to 24 figures — what's our net profit?",
]
DRILLS = [
    "what's our net profit?",
    "are we profitable this month?",
    "why is it negative?",
    "what's our EBITDA by state?",
]


def main():
    pw = os.environ.get("RYDEL_PASSWORD")
    if not pw:
        print("RYDEL_PASSWORD not in env — run under `railway run`", file=sys.stderr)
        return 2
    s = requests.Session()
    r = s.post(BASE + "/dashboard/login",
               data={"username": "rydel", "password": pw}, timeout=30,
               allow_redirects=False)
    if r.status_code not in (200, 302):
        print(f"login failed: {r.status_code}", file=sys.stderr)
        return 2

    transcript, history, fails = [], [], []

    def ask(q):
        history.append({"role": "user", "content": q})
        resp = s.post(BASE + "/dashboard/api/chat",
                      json={"history": history}, timeout=120).json()
        reply = resp.get("reply") or ""
        history.append({"role": "assistant", "content": reply})
        transcript.append({"q": q, "a": reply, "intent": resp.get("intent")})
        return reply

    a1 = ask(THREAD[0])
    if not a1.startswith("Yes") and not a1.startswith("No"):
        fails.append("Q1 did not answer the word first")
    if "Answered as:" not in a1:
        fails.append("Q1 has no answered-as line")
    a2 = ask(THREAD[1])
    if re.search(r"can't back|won'?t\b|refus", a2.split("Answered as:")[0], re.I):
        fails.append("Q2 read as a refusal")
    if a2.count("$") < 2:
        fails.append("Q2 lacks the two dollar figures")

    for q in DRILLS:
        a = ask(q)
        if not a:
            fails.append(f"no answer to {q!r}")
    if transcript and "isn't a metric the engine computes" not in transcript[-1]["a"]:
        fails.append("the decoy was not declined")

    out = {"base": BASE, "transcript": transcript, "fails": fails}
    d = os.path.join(os.path.dirname(__file__), "..", "dashboard", "evidence")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "replay-witnessed-thread.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    for t in transcript:
        print("=" * 72)
        print("Q:", t["q"])
        print("A:", t["a"])
    print(("\nREPLAY PASS — " if not fails else
           f"\nREPLAY FAIL ({fails}) — ") + path)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
