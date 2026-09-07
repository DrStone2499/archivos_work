"""Hilo unico que captura, detecta y decide cuando leer la etiqueta.

La deteccion corre continua (barata). El OCR corre solo cuando la caja
lleva N frames quieta, o cuando el operador lo pide. Asi la UI no se traba.
"""
import base64
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np

import settings
from app.paths import resource, writable
from resources import detector_lib, ocr_lib
from resources.camera_lib import CameraStream


def _encode_jpeg(frame: np.ndarray, quality: int, max_width: int) -> str:
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return ""
    return base64.b64encode(buf).decode("ascii")


def _draw(frame, detections, primary_id):
    out = frame.copy()
    for i, d in enumerate(detections):
        color = (0, 220, 120) if i == primary_id else (140, 140, 140)
        cv2.rectangle(out, (d.box.x1, d.box.y1), (d.box.x2, d.box.y2), color, 3)
        for lab in d.labels:
            cv2.rectangle(out, (lab.x1, lab.y1), (lab.x2, lab.y2), (60, 180, 255), 2)
    return out


class Pipeline:
    def __init__(self, config: dict):
        self.config = config
        self.pipe_cfg = config.get("pipeline", {})
        self.stream = CameraStream(config["camera"])
        self.detector = None
        self.ocr = ocr_lib.OcrEngine(config["ocr"])

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

        self.frame_b64 = ""
        self.detections = []
        self.status = "iniciando"
        self.error = ""
        self.stable_count = 0
        self._last_center = None
        self._read_request = threading.Event()
        self.last_result = None   # {"fields":..., "text":..., "crop_path":...}
        self.fps = 0.0

    # ---------- ciclo de vida ----------
    def start(self):
        self.stream.start()
        model_path = self.config["detector"]["model_path"]
        if not os.path.isabs(model_path):
            candidate = resource(model_path)
            model_path = candidate if os.path.exists(candidate) else model_path
        self.detector = detector_lib.Detector(self.config["detector"], model_path)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.stream.stop()

    def request_read(self):
        self._read_request.set()

    # ---------- bucle ----------
    def _loop(self):
        last_tick = time.time()
        while not self._stop.is_set():
            frame = self.stream.latest()
            if frame is None:
                self.status = "sin senal"
                self.error = self.stream.error or "Esperando camara"
                time.sleep(0.2)
                continue

            try:
                detections = self.detector.detect(frame)
            except Exception as exc:
                self.error = f"Deteccion: {exc}"
                time.sleep(0.5)
                continue

            target = detector_lib.primary(detections)
            primary_id = detections.index(target) if target else -1
            self._update_stability(target)

            should_read = self._read_request.is_set() or (
                self.pipe_cfg.get("auto_read", True)
                and target is not None
                and self.stable_count == self.pipe_cfg.get("stable_frames", 8)
            )
            if should_read and target is not None:
                self._read_request.clear()
                self._read_label(frame, target)

            annotated = _draw(frame, detections, primary_id)
            b64 = _encode_jpeg(annotated,
                               self.pipe_cfg.get("stream_quality", 70),
                               self.pipe_cfg.get("stream_max_width", 1024))

            now = time.time()
            fps = 1.0 / max(now - last_tick, 1e-3)
            last_tick = now

            with self._lock:
                self.frame_b64 = b64
                self.detections = detections
                self.fps = round(0.7 * self.fps + 0.3 * fps, 1)
                self.error = ""
                if target is None:
                    self.status = "buscando caja"
                elif not target.labels:
                    self.status = "caja sin etiqueta visible"
                elif self.stable_count >= self.pipe_cfg.get("stable_frames", 8):
                    self.status = "etiqueta lista"
                else:
                    self.status = "estabilizando"

    def _update_stability(self, target):
        if target is None:
            self.stable_count = 0
            self._last_center = None
            return
        cx, cy = target.box.center
        if self._last_center is None:
            self.stable_count = 1
        else:
            moved = abs(cx - self._last_center[0]) + abs(cy - self._last_center[1])
            self.stable_count = self.stable_count + 1 if moved < 25 else 0
        self._last_center = (cx, cy)

    def _read_label(self, frame, target):
        crops = [lab.crop(frame) for lab in target.labels] or [target.box.crop(frame)]
        lines = []
        for crop in crops:
            lines.extend(self.ocr.read(crop))

        fields = ocr_lib.extract_fields(lines)
        text = "\n".join(l["text"] for l in lines)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        crop_path = writable(settings.CROPS_DIR, f"{stamp}.jpg")
        cv2.imwrite(crop_path, crops[0])

        with self._lock:
            self.last_result = {
                "fields": fields,
                "text": text,
                "crop_path": crop_path,
                "crop_b64": _encode_jpeg(crops[0], 80, 640),
                "read_at": datetime.now().isoformat(timespec="seconds"),
            }

    # ---------- lectura para la UI ----------
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "frame": self.frame_b64,
                "status": self.status,
                "error": self.error,
                "fps": self.fps,
                "stable": self.stable_count,
                "boxes": [d.as_dict() for d in self.detections],
                "result": self.last_result,
            }
