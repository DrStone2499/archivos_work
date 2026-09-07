import json
import time

from flask import Blueprint, Response, current_app, jsonify, render_template, request

import settings
from app import config_loader
from app.paths import resource
from resources import printer_lib, storage_lib

bp = Blueprint("main", __name__)


def pipe():
    return current_app.config["PIPELINE"]


@bp.route("/")
def index():
    return render_template(
        "index.html",
        app_name=settings.APP_NAME,
        version=settings.VERSION,
        fields=settings.FIELDS,
    )


@bp.route("/api/stream")
def stream():
    """SSE: un evento por frame con imagen anotada, estado y ultima lectura."""
    def generate():
        yield f"retry: {settings.SSE_RETRY_MS}\n\n"
        last_read_at = None
        while True:
            snap = pipe().snapshot()
            result = snap.get("result")
            # La lectura completa solo se manda cuando cambia; el frame va siempre.
            if result and result.get("read_at") == last_read_at:
                snap["result"] = None
            elif result:
                last_read_at = result.get("read_at")
            yield f"data: {json.dumps(snap)}\n\n"
            time.sleep(0.08)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/api/read", methods=["POST"])
def read_now():
    pipe().request_read()
    return jsonify({"ok": True})


@bp.route("/api/relabel", methods=["POST"])
def relabel():
    data = request.get_json(force=True) or {}
    values = data.get("fields", {})

    missing = [f["label"] for f in settings.FIELDS
               if f["required"] and not str(values.get(f["key"], "")).strip()]
    if missing:
        return jsonify({"ok": False, "error": f"Faltan campos: {', '.join(missing)}"}), 400

    cfg = config_loader.load()
    printed = False
    if cfg["printer"].get("enabled", False):
        try:
            zpl = printer_lib.render_zpl(resource(cfg["printer"]["template"]), values)
            printer_lib.send(zpl, cfg["printer"]["host"], cfg["printer"]["port"],
                             cfg["printer"].get("timeout_s", 5))
            printed = True
        except printer_lib.PrinterError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    record_id = storage_lib.save_relabel(
        fields=values,
        ocr_text=data.get("ocr_text", ""),
        crop_path=data.get("crop_path", ""),
        operator=data.get("operator", ""),
        printed=printed,
    )
    return jsonify({"ok": True, "id": record_id, "printed": printed})


@bp.route("/api/history")
def history():
    return jsonify(storage_lib.recent(25))


@bp.route("/api/config", methods=["GET", "POST"])
def config_endpoint():
    if request.method == "POST":
        config_loader.save(request.get_json(force=True))
        return jsonify({"ok": True, "restart_required": True})
    return jsonify(config_loader.load())
