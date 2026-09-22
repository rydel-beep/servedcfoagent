"""one_brain_gate.py — PROVE THE DOCK IS THE SAME EDITH, NOT A SECOND ONE.

The claim under test: the dock is a new CHANNEL on the existing brain — its own
thread, shared memory — exactly as the Timeline bridge is. If that is true, then
something said to her in the dock must be recallable from a different channel,
because both channels write to and read from one memory.

The drill, on production, in one owner session:

  1. say a distinctive thing on the DOCK channel  (channel="dashboard")
  2. wait for the fire-and-forget memory write to land
  3. ask for it back on a DIFFERENT channel        (channel omitted -> "text")
  4. the answer must contain what was said in step 1

Step 3 deliberately does NOT go through the Timeline bridge: reaching that route
would require minting a bridge token, which this build is forbidden to do. The
bridge is the same code path by construction — `bridge_chat_stream` calls the
same `chat_stream_response` with channel="timeline" — so proving cross-channel
recall between "dashboard" and "text" proves the shared-memory property the
bridge relies on, without minting anything.

Run it under `railway run` so the owner credential is injected, never typed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import requests

BASE = os.environ.get("GATE_BASE", "https://web-production-16b16.up.railway.app")
USER = os.environ.get("GATE_OWNER_USER", "rydel")
PW = os.environ.get("GATE_OWNER_PASSWORD") or os.environ.get("RYDEL_PASSWORD")

# A phrase that cannot already be in the store, and cannot be guessed from data.
MARK = "harbour lantern"
SAY = ("For this thread, note that I'm calling this quarter's ad experiment "
       "the harbour lantern test. Just acknowledge it — no numbers needed.")
ASK = ("Earlier I told you what I'm calling this quarter's ad experiment. "
       "What name did I give it?")


def login(s):
    s.post(BASE + "/dashboard/login",
           data={"username": USER, "password": PW}, timeout=30)


def say(s, message, channel=None):
    """POST one turn to the SSE chat route and return the assembled reply."""
    body = {"history": [{"role": "user", "content": message}], "voice": False}
    if channel:
        body["channel"] = channel
    r = s.post(BASE + "/dashboard/api/chat-stream", json=body, stream=True, timeout=180)
    if r.status_code != 200:
        return "", r.status_code
    out, buf = "", ""
    for chunk in r.iter_content(chunk_size=None):
        buf += chunk.decode("utf-8", "replace")
        frames = buf.split("\n\n")
        buf = frames.pop()
        for f in frames:
            ev = (re.search(r"^event:\s*(.+)$", f, re.M) or [None, ""])[1]
            dl = (re.search(r"^data:\s*([\s\S]+)$", f, re.M) or [None, ""])[1]
            if not ev or not dl:
                continue
            try:
                p = json.loads(dl)
            except Exception:
                continue
            if ev == "delta" and p.get("text"):
                out += p["text"]
            elif ev == "done":
                out = p.get("reply") or out
    return out, 200


def main():
    if not PW:
        print("no owner password in env — run under `railway run`", file=sys.stderr)
        return 2
    s = requests.Session()
    login(s)

    report = {"base": BASE, "mark": MARK, "steps": []}
    fails = []

    dock_reply, code = say(s, SAY, channel="dashboard")
    report["steps"].append({"step": "say on the dock channel", "http": code,
                            "reply": dock_reply[:300]})
    if code != 200 or not dock_reply:
        fails.append("the dock channel did not answer (http %s)" % code)

    # the memory write is fire-and-forget on a daemon thread — give it room
    time.sleep(20)

    recall_reply, code = say(s, ASK)  # no channel -> "text", a DIFFERENT thread
    report["steps"].append({"step": "ask on the text channel", "http": code,
                            "reply": recall_reply[:400]})
    if code != 200:
        fails.append("the text channel did not answer (http %s)" % code)
    elif MARK not in recall_reply.lower():
        fails.append("the other channel did not recall %r — it said: %s"
                     % (MARK, recall_reply[:200]))

    report["fails"] = fails
    out = os.path.join(os.path.dirname(__file__), "..", "dashboard", "evidence")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "one-brain.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    print(("ONE-BRAIN PASS — " if not fails else "ONE-BRAIN FAIL — ") + path)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
