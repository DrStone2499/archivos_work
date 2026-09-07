"""Lectura de la etiqueta y extraccion de campos."""
import re
from typing import Dict, List

import cv2
import numpy as np

import settings


def preprocess(crop: np.ndarray, upscale: float = 2.0) -> np.ndarray:
    """Etiquetas impresas: escala de grises, mas resolucion y contraste local."""
    if crop is None or crop.size == 0:
        return crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if upscale and upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.bilateralFilter(gray, 5, 50, 50)
    return gray


def deskew(gray: np.ndarray, max_angle: float = 15.0) -> np.ndarray:
    """Endereza la etiqueta si viene girada unos grados."""
    if gray is None or gray.size == 0:
        return gray
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 120, minLineLength=gray.shape[1] // 3, maxLineGap=20)
    if lines is None:
        return gray
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) < max_angle:
            angles.append(angle)
    if not angles:
        return gray
    angle = float(np.median(angles))
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


class OcrEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.min_conf = cfg.get("min_confidence", 0.35)
        self.upscale = cfg.get("upscale", 2.0)
        self._reader = None

    def _ensure_reader(self):
        if self._reader is None:
            import easyocr  # import tardio: descarga/carga pesos la primera vez
            self._reader = easyocr.Reader(self.cfg.get("languages", ["es", "en"]), gpu=False)
        return self._reader

    def read(self, crop: np.ndarray) -> List[dict]:
        image = deskew(preprocess(crop, self.upscale))
        reader = self._ensure_reader()
        out = []
        for bbox, text, conf in reader.readtext(image):
            if conf >= self.min_conf and text.strip():
                out.append({"text": text.strip(), "conf": round(float(conf), 3)})
        return out


def extract_fields(lines: List[dict]) -> Dict[str, dict]:
    """Aplica los patrones de settings.FIELDS al texto leido."""
    joined = "\n".join(l["text"] for l in lines).upper()
    fields = {}
    for spec in settings.FIELDS:
        value, conf = "", 0.0
        match = re.search(spec["pattern"], joined, re.IGNORECASE)
        if match:
            value = (match.group(1) if match.groups() else match.group(0)).strip()
            conf = max((l["conf"] for l in lines if value in l["text"].upper()), default=0.5)
        fields[spec["key"]] = {
            "label": spec["label"],
            "value": value,
            "confidence": round(conf, 3),
            "required": spec["required"],
            "source": "ocr" if value else "vacio",
        }
    return fields
