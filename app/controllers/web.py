from __future__ import annotations

from flask import Blueprint, render_template

from ..models.store import store


bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    return render_template("index.html", **store.snapshot())
