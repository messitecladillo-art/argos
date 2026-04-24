from __future__ import annotations

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

from .services import ProfileError, store


bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    return render_template("index.html", **store.snapshot())


@bp.get("/api/dashboard")
def dashboard():
    return jsonify(store.snapshot())


@bp.get("/api/profiles")
def list_profiles():
    return jsonify({"profiles": store.list_profiles()})


@bp.post("/api/agents")
def create_agent():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    profile_name = (payload.get("profile_name") or "").strip()
    role = (payload.get("role") or "specialist").strip()
    description = (payload.get("description") or "").strip()
    skills_raw = payload.get("skills") or []
    if isinstance(skills_raw, str):
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
    else:
        skills = [str(s).strip() for s in skills_raw if str(s).strip()]
    clone_from = (payload.get("clone_from") or "").strip() or None
    try:
        agent = store.create_agent(
            name=name,
            profile_name=profile_name,
            role=role,
            description=description,
            skills=skills,
            clone_from=clone_from,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except ProfileError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "agent": agent}), 201


@bp.post("/api/messages")
def create_message():
    payload = request.get_json(silent=True) or {}
    content = (payload.get("content") or "").strip()
    to_agent_id = payload.get("to_agent_id") or ""
    if not content:
        return jsonify({"ok": False, "error": "content is required"}), 400
    if not to_agent_id:
        return jsonify({"ok": False, "error": "to_agent_id is required"}), 400
    try:
        message = store.add_message(content, to_agent_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "message": message}), 201


@bp.get("/api/events/stream")
def event_stream():
    subscriber = store.subscribe()

    @stream_with_context
    def generate():
        try:
            yield ": connected\n\n"
            while True:
                yield subscriber.get()
        finally:
            store.unsubscribe(subscriber)

    return Response(generate(), mimetype="text/event-stream")
