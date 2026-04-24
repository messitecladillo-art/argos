from __future__ import annotations

from flask import Blueprint, Response, stream_with_context

from ..models.store import store


bp = Blueprint("events", __name__, url_prefix="/api")


@bp.get("/events/stream")
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
