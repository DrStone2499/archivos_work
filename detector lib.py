"""Deteccion con Ultralytics: cajas y etiquetas, y la relacion entre ambas."""
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    conf: float
    cls_name: str

    @property
    def center(self):
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self):
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

    def contains(self, other: "Box") -> float:
        """Fraccion de 'other' que cae dentro de este box."""
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        return inter / other.area if other.area else 0.0

    def crop(self, image: np.ndarray, pad: int = 6) -> np.ndarray:
        h, w = image.shape[:2]
        return image[max(0, self.y1 - pad):min(h, self.y2 + pad),
                     max(0, self.x1 - pad):min(w, self.x2 + pad)]

    def as_dict(self):
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2,
                "conf": round(self.conf, 3), "cls": self.cls_name}


@dataclass
class DetectedBox:
    box: Box
    labels: List[Box] = field(default_factory=list)

    def as_dict(self):
        d = self.box.as_dict()
        d["labels"] = [l.as_dict() for l in self.labels]
        return d


class Detector:
    def __init__(self, cfg: dict, model_path: str):
        from ultralytics import YOLO  # import tardio: carga torch, es lento

        self.model = YOLO(model_path)
        self.conf = cfg.get("conf", 0.45)
        self.iou = cfg.get("iou", 0.5)
        self.imgsz = cfg.get("imgsz", 960)
        self.device = cfg.get("device", "cpu")
        self.cls_box = cfg.get("class_box", "caja")
        self.cls_label = cfg.get("class_label", "etiqueta")

    def detect(self, frame: np.ndarray) -> List[DetectedBox]:
        result = self.model.predict(
            frame, conf=self.conf, iou=self.iou, imgsz=self.imgsz,
            device=self.device, verbose=False,
        )[0]

        names = result.names
        boxes, labels = [], []
        for b in result.boxes:
            x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
            item = Box(x1, y1, x2, y2, float(b.conf[0]), names[int(b.cls[0])])
            (boxes if item.cls_name == self.cls_box else labels).append(item)

        detected = [DetectedBox(box=b) for b in sorted(boxes, key=lambda b: -b.area)]

        # Cada etiqueta se asigna a la caja que mas la contiene.
        for lab in labels:
            best, best_ratio = None, 0.5
            for d in detected:
                ratio = d.box.contains(lab)
                if ratio > best_ratio:
                    best, best_ratio = d, ratio
            if best is not None:
                best.labels.append(lab)
            else:
                # Etiqueta suelta (caja fuera de encuadre): se trata como su propia caja.
                detected.append(DetectedBox(box=lab, labels=[lab]))

        return detected


def primary(detections: List[DetectedBox]) -> Optional[DetectedBox]:
    """La caja de interes: la mas grande que tenga al menos una etiqueta."""
    with_labels = [d for d in detections if d.labels]
    if not with_labels:
        return None
    return max(with_labels, key=lambda d: d.box.area)
