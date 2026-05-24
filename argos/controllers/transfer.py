from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Blueprint, after_this_request, jsonify, request, send_file

from ..services import transfer
from ..models.store import store


bp = Blueprint("transfer", __name__, url_prefix="/api/transfer")


def _json_error(exc: Exception, status_code: int = 500):
    code = getattr(exc, "status_code", status_code)
    return jsonify({"ok": False, "error": str(exc)}), code


@bp.post("/export")
def export_team():
    payload = request.get_json(silent=True) or {}
    options = payload.get("options") or {}
    try:
        archive_path = transfer.export_agents(
            payload.get("profile_names") or [],
            inline_skill_files=bool(options.get("inline_skill_files", True)),
            include_workspace=bool(options.get("include_workspace", False)),
        )
    except Exception as exc:  # noqa: BLE001
        return _json_error(exc, 500)

    @after_this_request
    def cleanup(response):
        try:
            archive_path.unlink(missing_ok=True)
        except OSError:
            pass
        return response

    return send_file(
        archive_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=archive_path.name,
    )


@bp.post("/inspect")
def inspect_team_archive():
    archive_path = None
    try:
        archive_path = _save_uploaded_archive()
        return jsonify(transfer.inspect_archive(archive_path))
    except Exception as exc:  # noqa: BLE001
        return _json_error(exc, 500)
    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)


@bp.post("/import")
def import_team_archive():
    archive_path = None
    try:
        archive_path = _save_uploaded_archive()
        return jsonify(transfer.import_archive(archive_path, store=store))
    except Exception as exc:  # noqa: BLE001
        return _json_error(exc, 500)
    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)


def _save_uploaded_archive() -> Path:
    file = request.files.get("file")
    if file is None or not file.filename:
        raise transfer.TransferError("file is required")
    suffix = transfer.EXPORT_SUFFIX if file.filename.endswith(transfer.EXPORT_SUFFIX) else ".zip"
    handle = tempfile.NamedTemporaryFile(prefix="team-transfer-", suffix=suffix, delete=False)
    path = Path(handle.name)
    handle.close()
    file.save(path)
    return path
