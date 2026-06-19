"""
dashboard/memory_routes.py
--------------------------
EDITH memory management UI + API (Phase 5). Self-contained blueprint registered at
/dashboard/memory — touches none of the chat-path files. All endpoints behind dashboard auth.

Rydel curates what EDITH "knows": view conversations/transcripts, edit/delete/toggle distilled
facts, forget a conversation, or clear all memory (privacy control, with a confirm on the client).
"""
from __future__ import annotations

import logging

from flask import Blueprint, render_template, request, jsonify

from dashboard.auth import require_auth
import db
import memory

logger = logging.getLogger(__name__)

bp = Blueprint("memory", __name__, template_folder="templates")


def _no_store(payload, status=200):
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp, status


@bp.route("/")
@require_auth
def memory_page():
    return render_template("memory.html")


@bp.route("/api/status")
@require_auth
def api_status():
    return _no_store(memory.memory_status())


@bp.route("/api/conversations")
@require_auth
def api_conversations():
    include_archived = request.args.get("archived") == "1"
    rows = db.list_conversations(limit=100, include_archived=include_archived)
    return _no_store({"conversations": rows, "memory": memory.memory_status()})


@bp.route("/api/conversation/<int:cid>")
@require_auth
def api_transcript(cid):
    return _no_store({"id": cid, "messages": db.get_transcript(cid)})


@bp.route("/api/conversation/<int:cid>/archive", methods=["POST"])
@require_auth
def api_archive(cid):
    ok = db.archive_conversation(cid)
    return _no_store({"ok": ok}, 200 if ok else 404)


@bp.route("/api/conversation/<int:cid>", methods=["DELETE"])
@require_auth
def api_delete_conversation(cid):
    ok = db.delete_conversation(cid)
    return _no_store({"ok": ok}, 200 if ok else 404)


@bp.route("/api/facts")
@require_auth
def api_facts():
    include_inactive = request.args.get("inactive") == "1"
    facts = db.list_facts(include_inactive=include_inactive)
    # group by category for the UI
    grouped: dict[str, list] = {}
    for f in facts:
        grouped.setdefault(f["category"], []).append(f)
    return _no_store({"facts": facts, "by_category": grouped})


@bp.route("/api/facts/<int:fid>", methods=["POST"])
@require_auth
def api_update_fact(fid):
    data = request.get_json(silent=True) or {}
    ok = db.update_fact(
        fid,
        fact=data.get("fact"),
        category=data.get("category"),
        active=data.get("active"),
    )
    return _no_store({"ok": ok}, 200 if ok else 404)


@bp.route("/api/facts/<int:fid>", methods=["DELETE"])
@require_auth
def api_delete_fact(fid):
    ok = db.delete_fact(fid)
    return _no_store({"ok": ok}, 200 if ok else 404)


@bp.route("/api/clear-all", methods=["POST"])
@require_auth
def api_clear_all():
    data = request.get_json(silent=True) or {}
    if data.get("confirm") != "CLEAR":
        return _no_store({"ok": False, "error": "confirmation required"}, 400)
    include_transcripts = bool(data.get("include_transcripts", True))
    ok = db.clear_all_memory(include_transcripts=include_transcripts)
    return _no_store({"ok": ok}, 200 if ok else 500)
