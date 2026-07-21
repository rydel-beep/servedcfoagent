"""
quarterly_review.py
-------------------
Orchestrator: assemble a full quarterly review (current pack + prior-quarter pack + same-quarter-
prior-year pack + QoQ/YoY comparisons + the 3x model) for one quarter. Shared by the JSON endpoint
(chat answers, "how did Q1 compare to last year?") and the PDF generator — so both read identical
numbers. Pure assembly over the deterministic engines; no fabrication.
"""
from __future__ import annotations

import logging

import quarterly_pack as qp
import quarterly_compare as qc
import three_x_model

logger = logging.getLogger(__name__)


def build_review(year: int, q: int, assumptions: dict | None = None) -> dict:
    """The complete review object for calendar quarter q of `year`."""
    current = qp.quarter_pack(year, q)

    py, pq = qp.prev_quarter(year, q)
    try:
        prior_q = qp.quarter_pack(py, pq)
    except Exception as e:
        logger.info("prior-quarter pack failed: %s", e)
        prior_q = None

    # same quarter, previous year (YoY)
    try:
        prior_y = qp.quarter_pack(year - 1, q)
    except Exception as e:
        logger.info("prior-year pack failed: %s", e)
        prior_y = None

    qoq = qc.compare(current, prior_q, "QoQ")
    yoy = qc.compare(current, prior_y, "YoY")

    threex = three_x_model.build_3x(current, assumptions)

    return {
        "quarter": {"year": year, "q": q, "label": qp.quarter_label(year, q)},
        "current": current,
        "prior_quarter": prior_q,
        "prior_year": prior_y,
        "comparisons": {"qoq": qoq, "yoy": yoy},
        "three_x": threex,
        "generated_at": current.get("generated_at"),
        "convention": "calendar",
    }


def default_review(assumptions: dict | None = None) -> dict:
    """The last completed calendar quarter — the default the button generates."""
    y, q = qp.last_completed_quarter()
    return build_review(y, q, assumptions)
