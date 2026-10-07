"""routes.py — /scoreboard: the page, its data, and the journaled decisions.

Owner + Piolo (finance-grade). The read-only gate account can look and can't
act (structural, in dashboard.auth). Every decision a person makes here —
confirming a link, a contract value, a name — is journaled with who, when and
their words; nothing here ever writes to GHL, Stripe, Xero, Meta or the tracker.
"""
from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, redirect, render_template, request

from dashboard.auth import current_actor, require_owner, require_owner_strict

from . import build, store, sync

logger = logging.getLogger(__name__)

bp = Blueprint("scoreboard", __name__, template_folder="templates")

_KEY = re.compile(r"^(link:[A-Za-z0-9_\-]{6,80}"
                  r"|deal:[A-Za-z0-9]{10,40}:(contract_ex|term|closer|setter|package)"
                  r"|user:[A-Za-z0-9]{10,40}"
                  r"|calendar:[A-Za-z0-9]{10,40})$")


def _window_args():
    return (request.args.get("window") or "month", request.args.get("start"), request.args.get("end"))


@bp.route("")
@bp.route("/")
@require_owner
def page():
    try:
        data = build.scoreboard(*_window_args())
        err = None
    except Exception as e:  # noqa: BLE001
        logger.exception("scoreboard build failed")
        data, err = None, str(e)[:300]
    return render_template("scoreboard.html", data=data, error=err,
                           actor=current_actor().get("display") or "")


@bp.route("/api", methods=["GET"])
@require_owner
def api():
    return jsonify(build.scoreboard(*_window_args()))


@bp.route("/api/raw-counts", methods=["GET"])
@require_owner
def raw_counts():
    """Phase 0: row counts per source per month, and freshness."""
    from . import rules as R
    out = {}
    for s, k in build.RAW_KINDS:
        rows = store.read(s, k)
        by_m: dict[str, int] = {}
        for rid, r in rows.items():
            when = (r.get("dateAdded") or r.get("startTime") or r.get("createdAt") or r.get("created")
                    or r.get("date_start") or r.get("DateString") or (rid if k == "pnl_month" else None))
            d = R.syd_date(when) if k != "pnl_month" else None
            m = f"{d:%Y-%m}" if d else (str(rid)[:7] if k == "pnl_month" else "undated")
            by_m[m] = by_m.get(m, 0) + 1
        out[f"{s}.{k}"] = {"total": len(rows), "2026-09": by_m.get("2026-09", 0), "2026-10": by_m.get("2026-10", 0)}
    from helpers import now_sydney
    return jsonify({"counts": out, "freshness": build.freshness(store.sync_state(), now_sydney())})


@bp.route("/api/confirm", methods=["POST"])
@require_owner
def confirm():
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "")
    if not _KEY.match(key):
        return jsonify({"ok": False, "error": "that isn't something the scoreboard can record"}), 400
    data = body.get("data")
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "nothing to record"}), 400
    if key.startswith("deal:") and key.endswith(":contract_ex"):
        try:
            v = float(str(data.get("value")).replace("$", "").replace(",", ""))
            if v <= 0:
                raise ValueError
            data = {"value": f"{v:.2f}"}
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "a contract value must be a dollar amount"}), 400
    if key.startswith("deal:") and key.endswith(":term"):
        try:
            data = {"value": int(data.get("value"))}
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "a term must be a number of months"}), 400
    if key.startswith("user:") or key.split(":")[-1] in ("closer", "setter", "package"):
        v = str(data.get("value") if not key.startswith("user:") else data.get("name") or data.get("value") or "").strip()
        if not v or len(v) > 60:
            return jsonify({"ok": False, "error": "type a name"}), 400
        data = {"name": v} if key.startswith("user:") else {"value": v}
    if key.startswith("calendar:"):
        data = {"counts": bool(data.get("counts", data.get("value")))}
    if key.startswith("link:"):
        data = {k: data[k] for k in ("opp_id", "not_client", "client") if k in data}
        if not data:
            return jsonify({"ok": False, "error": "say which deal this payment belongs to"}), 400
    actor = current_actor().get("display") or current_actor().get("user") or "unknown"
    words = str(body.get("words") or "").strip()[:500]
    rec = store.journal_add(actor, "confirm", key, {**data, "words": words})
    build.invalidate()
    return jsonify({"ok": True, "recorded": rec})


@bp.route("/api/undo", methods=["POST"])
@require_owner
def undo():
    key = str((request.get_json(silent=True) or {}).get("key") or "")
    if not _KEY.match(key):
        return jsonify({"ok": False, "error": "unknown key"}), 400
    actor = current_actor().get("display") or "unknown"
    store.journal_add(actor, "undo", key, {})
    build.invalidate()
    return jsonify({"ok": True})


@bp.route("/api/journal", methods=["GET"])
@require_owner
def journal():
    return jsonify({"journal": store.journal()})


@bp.route("/api/sync", methods=["POST"])
@require_owner
def sync_now():
    """Re-read one source now (read-only pull into the scoreboard's tables)."""
    job = str((request.get_json(silent=True) or {}).get("job") or "")
    if job not in sync.JOBS:
        return jsonify({"ok": False, "error": "unknown source"}), 400
    if not store.claim(job, 120):
        return jsonify({"ok": False, "error": "that source is already being read — try again in a minute"})
    return jsonify(sync.run(job))


# Xero: the reconnect that adds read access to bank transactions and invoices.
# Rydel logs in to Xero himself and approves; nothing is created here.
XERO_SCOREBOARD_SCOPES = ("offline_access accounting.reports.profitandloss.read "
                          "accounting.reports.banksummary.read accounting.reports.balancesheet.read "
                          "accounting.banktransactions.read accounting.invoices.read")


@bp.route("/xero/connect", methods=["GET"])
@require_owner_strict
def xero_connect():
    from config import XERO_CLIENT_ID, XERO_REDIRECT_URI
    if not XERO_CLIENT_ID or not XERO_REDIRECT_URI:
        return jsonify({"error": "Xero is not configured on the server"}), 500
    return redirect("https://login.xero.com/identity/connect/authorize?response_type=code"
                    f"&client_id={XERO_CLIENT_ID}&redirect_uri={XERO_REDIRECT_URI}"
                    f"&scope={XERO_SCOREBOARD_SCOPES.replace(' ', '+')}")
