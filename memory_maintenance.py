"""
memory_maintenance.py
---------------------
THE NIGHTLY MEMORY JOB (VOICE_MEMORY_SELFIMPROVE_REPORT D3 — the debt on record
since the content-review build, now paid down PROPERLY and kept down).

DOCTRINE (non-negotiable):
  · NEVER DELETES. Merge/supersede/demote all set active=FALSE (the archive tier —
    out of the hot budget, retrievable by search, restorable by id). DELETE stays
    a human-only surgical tool elsewhere.
  · EVERY action journaled (kv memory:maintenance_journal) — reversible ('restore
    memory fact #N').
  · UNCERTAIN pairs are never guessed: they become confirmation cards
    (kv memory:confirm_cards) that EDITH surfaces; Rydel rules.
  · THE BUDGET INVARIANT (from the content-review fix, now MAINTAINED, not
    one-shot): the hot fact block must fit its char budget with recall headroom —
    re-protected at every size by demoting the stalest low-weight tail.

Found at Phase 0 (2026-08-06): 175 active facts; top-60 rendered 7,034 chars vs
the 6,000 fact budget (9 facts silently trimmed per turn); 12 near-dup pairs;
decay never run since the store's birth.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_KV_JOURNAL = "memory:maintenance_journal"   # capped list, newest last
_KV_CARDS = "memory:confirm_cards"           # uncertain pairs awaiting Rydel
_KV_TICK = "memory:maintenance_tick"

MERGE_SIM = 0.75          # ≥ this (same category) → auto-merge, journaled
REVIEW_SIM = 0.55         # ≥ this but < MERGE_SIM → contradiction/near-dup review
STALE_DAYS = 45           # untouched this long AND low weight → demote to archive
DEMOTE_WEIGHT_MAX = 1.0
# a newer fact that explicitly marks transition may supersede its pair without asking
_TRANSITION_RE = re.compile(r"\b(previously|no longer|now on|changed to|was on|instead of|"
                            r"replaced|updated to|new salary|now at)\b", re.I)


def _journal(action: str, detail: str, ids: list[int]) -> None:
    import kv_store
    from helpers import now_sydney
    j = kv_store.get(_KV_JOURNAL) or []
    j.append({"ts": now_sydney().isoformat(timespec="seconds"), "action": action,
              "ids": ids, "detail": detail[:200]})
    kv_store.put(_KV_JOURNAL, j[-400:])


def journal(limit: int = 50) -> list[dict]:
    import kv_store
    return (kv_store.get(_KV_JOURNAL) or [])[-limit:]


def _pairs(min_sim: float) -> list[dict]:
    import db
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT a.id AS ia, b.id AS ib, similarity(a.fact, b.fact) AS s,
                   a.fact AS fa, b.fact AS fb, a.weight AS wa, b.weight AS wb,
                   a.created_at AS ca, b.created_at AS cb, a.category AS cat
            FROM memory_facts a JOIN memory_facts b
              ON a.id < b.id AND a.active AND b.active AND a.category = b.category
             AND similarity(a.fact, b.fact) >= %s
            ORDER BY s DESC LIMIT 60""", (min_sim,))
        return cur.fetchall()


def consolidate() -> dict:
    """Merge near-duplicates (≥MERGE_SIM); route the REVIEW band to supersession
    (only on an explicit transition marker in the newer fact) or a confirmation
    card. Nothing deleted, everything journaled."""
    import db
    merged, superseded, carded = 0, 0, 0
    import kv_store
    cards = kv_store.get(_KV_CARDS) or []
    known_pairs = {(c["ids"][0], c["ids"][1]) for c in cards if c.get("ids")}
    done_ids: set[int] = set()

    for p in _pairs(REVIEW_SIM):
        if p["ia"] in done_ids or p["ib"] in done_ids:
            continue
        # keep the newer fact (recency = the operative truth); the older archives
        newer, older = (p["ib"], p["ia"]) if p["cb"] >= p["ca"] else (p["ia"], p["ib"])
        newer_txt = p["fb"] if newer == p["ib"] else p["fa"]
        if p["s"] >= MERGE_SIM:
            kept_w = max(p["wa"], p["wb"]) + 0.5
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("UPDATE memory_facts SET active = FALSE WHERE id = %s", (older,))
                cur.execute("UPDATE memory_facts SET weight = %s WHERE id = %s", (kept_w, newer))
            _journal("merged", f"#{older} → #{newer} (sim {p['s']:.2f}): {newer_txt[:80]}",
                     [older, newer])
            merged += 1
            done_ids.update((p["ia"], p["ib"]))
        elif _TRANSITION_RE.search(newer_txt):
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("UPDATE memory_facts SET active = FALSE WHERE id = %s", (older,))
            _journal("superseded", f"#{older} superseded by #{newer} (transition marker, "
                                   f"sim {p['s']:.2f})", [older, newer])
            superseded += 1
            done_ids.update((p["ia"], p["ib"]))
        else:
            key = (p["ia"], p["ib"])
            if key not in known_pairs:
                cards.append({"ids": [p["ia"], p["ib"]], "sim": round(p["s"], 2),
                              "a": p["fa"][:140], "b": p["fb"][:140],
                              "question": "same fact / contradiction / genuinely different?"})
                known_pairs.add(key)
                carded += 1
    kv_store.put(_KV_CARDS, cards[-40:])
    return {"merged": merged, "superseded": superseded, "carded": carded}


def demote_stale() -> int:
    """Importance-weighted retention: stale low-value facts → the archive tier
    (active=FALSE, retrievable, restorable). NEVER deleted."""
    import db
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, fact FROM memory_facts
            WHERE active AND weight <= %s
              AND last_referenced_at < now() - (%s * interval '1 day')
            ORDER BY weight ASC, last_referenced_at ASC LIMIT 40""",
                    (DEMOTE_WEIGHT_MAX, STALE_DAYS))
        rows = cur.fetchall()
        for r in rows:
            cur.execute("UPDATE memory_facts SET active = FALSE WHERE id = %s", (r["id"],))
    for r in rows:
        _journal("demoted", f"#{r['id']} stale>{STALE_DAYS}d low-weight: {r['fact'][:80]}",
                 [r["id"]])
    return len(rows)


def enforce_budget() -> int:
    """THE INVARIANT: the hot fact block (top-60 render) must fit the fact budget
    (recall headroom reserved). Demote the stalest low-weight tail until it fits."""
    import db
    from config import MEMORY_MAX_CONTEXT_CHARS
    budget = MEMORY_MAX_CONTEXT_CHARS - 2000
    demoted = 0
    for _ in range(120):
        facts = db.active_facts(limit=60)
        used = sum(len(f"- [{f['category']}] {f['fact']}") + 1 for f in facts)
        if used <= budget or not facts:
            break
        tail = facts[-1]   # lowest weight, least-recently referenced of the hot set
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE memory_facts SET active = FALSE WHERE id = %s", (tail["id"],))
        _journal("demoted", f"#{tail['id']} demoted for budget ({used}>{budget}): "
                            f"{tail['fact'][:70]}", [tail["id"]])
        demoted += 1
    return demoted


def restore(fact_id: int) -> bool:
    """Reversibility: bring an archived fact back to the hot tier."""
    import db
    ok = db.update_fact(fact_id, active=True)
    if ok:
        _journal("restored", f"#{fact_id} restored to hot tier", [fact_id])
    return ok


def run() -> dict:
    """The nightly job: consolidate → demote stale → enforce the budget invariant."""
    import db
    if not db.db_configured():
        return {"skipped": "db offline"}
    c = consolidate()
    stale = demote_stale()
    budget = enforce_budget()
    out = {**c, "demoted_stale": stale, "demoted_for_budget": budget}
    _journal("run", f"nightly maintenance: {out}", [])
    logger.info("memory maintenance: %s", out)
    return out


def nightly_tick() -> bool:
    import kv_store
    from helpers import today_sydney
    if kv_store.get(_KV_TICK) == str(today_sydney()):
        return False
    try:
        run()
        kv_store.put(_KV_TICK, str(today_sydney()))
        return True
    except Exception as e:
        logger.warning("memory maintenance tick failed: %s", e)
        return False


def search_archived(text: str, limit: int = 3) -> list[dict]:
    """Archived facts stay retrievable: topical matches return labelled, on demand."""
    import db
    if not text or not db.db_configured():
        return []
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, fact, category, similarity(fact, %s) AS s
                FROM memory_facts WHERE active = FALSE AND similarity(fact, %s) >= 0.30
                ORDER BY s DESC LIMIT %s""", (text, text, limit))
            return cur.fetchall()
    except Exception as e:
        logger.info("search_archived failed: %s", e)
        return []


# ── EDITH: confirmation cards + journal + restore ────────────────────────────

_CARDS_RE = re.compile(r"memory (conflicts?|cards?|review)|any (memory )?(conflicts?|contradictions?)"
                       r"|conflicting (facts|memories)", re.I)
_JOURNAL_RE = re.compile(r"memory (maintenance|journal)|what did (the )?maintenance (do|change)", re.I)
_RESTORE_RE = re.compile(r"restore memory fact #?(\d+)", re.I)
_RESOLVE_RE = re.compile(r"memory card (\d+)\s*:?\s*keep\s*(a|b|both)", re.I)


def handle_memory_maintenance_command(text: str) -> tuple[str | None, bool]:
    import kv_store
    if not text:
        return None, False
    m = _RESTORE_RE.search(text)
    if m:
        fid = int(m.group(1))
        return (f"Restored fact #{fid} to the hot tier." if restore(fid)
                else f"Couldn't restore #{fid} — check the id."), True
    m = _RESOLVE_RE.search(text)
    if m:
        idx, keep = int(m.group(1)) - 1, m.group(2).lower()
        cards = kv_store.get(_KV_CARDS) or []
        if not (0 <= idx < len(cards)):
            return f"No memory card {idx + 1} — say 'memory conflicts' to list them.", True
        card = cards.pop(idx)
        import db
        if keep in ("a", "b"):
            drop_id = card["ids"][1] if keep == "a" else card["ids"][0]
            db.update_fact(drop_id, active=False)
            _journal("superseded", f"#{drop_id} archived by Rydel's card ruling "
                                   f"(kept {'A' if keep == 'a' else 'B'})", card["ids"])
            msg = f"Done — kept {'A' if keep == 'a' else 'B'}, archived the other (reversible)."
        else:
            _journal("kept_both", "Rydel ruled the pair genuinely different", card["ids"])
            msg = "Noted — both stay."
        kv_store.put(_KV_CARDS, cards)
        return msg, True
    if _CARDS_RE.search(text):
        cards = kv_store.get(_KV_CARDS) or []
        if not cards:
            return "No memory conflicts waiting on you — the sweep is clean.", True
        lines = [f"{len(cards)} pair(s) I won't guess on — rule each with "
                 f"'memory card N: keep A/B/both':"]
        for i, c in enumerate(cards[:6], 1):
            lines.append(f"{i}. (sim {c['sim']}) A: {c['a']} | B: {c['b']}")
        return "\n".join(lines), True
    if _JOURNAL_RE.search(text):
        j = journal(8)
        if not j:
            return "The maintenance job hasn't run yet — it runs nightly.", True
        lines = ["Recent memory maintenance (nothing is ever deleted — all reversible):"]
        for e in reversed(j):
            lines.append(f"• [{e['ts'][:16]}] {e['action']}: {e['detail']}")
        return "\n".join(lines), True
    return None, False
