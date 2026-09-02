"""
hsv.py - Inspección de pegamento por segmentación HSV + densidad de bordes.

Correcciones sobre la versión original:

  1. cv2.contourArea([x1,y1,x2,y2]) era inválido: contourArea espera un
     contorno Nx2, no cuatro escalares. El área de un rectángulo se calcula
     directamente.
  2. area_roi se imprimía fuera del bucle -> NameError si no hay ROIs.
  3. Los ROI no se recortaban a la imagen. Con offsets negativos numpy
     recortaba desde el extremo contrario en silencio, y con ROIs fuera de
     la imagen roi_mask.size era 0 -> ZeroDivisionError.
  4. Coordenadas float del JSON rompían el slicing.
  5. Umbrales y parámetros de Canny estaban fijos en el código; ahora salen
     del propio ROI_FILE con los mismos valores por defecto.
  6. El JSON se releía en cada frame; ahora se cachea por mtime.
  7. 'step == 110' acoplaba el módulo al valor del PLC; ahora hay un mapa de
     recetas y un aviso explícito si llega un step desconocido.
"""

import json
import os
import threading

import cv2
import numpy as np

from static.config.settings import ROI_FILE, REF_PATH1, REF_PATH2


# --------------------------------------------------------------------------
# Parámetros por defecto (se pueden sobrescribir desde ROI_FILE)
# --------------------------------------------------------------------------

DEFAULTS = {
    "ratio_threshold": 0.15,
    "edge_threshold": 0.04,
    "canny_low": 50,
    "canny_high": 150,
    "morph_kernel": 5,
    # "or"  -> OK si el área de pegamento O la textura superan el umbral
    #          (comportamiento original)
    # "and" -> OK sólo si ambas lo superan
    # "ratio" / "edge" -> usar un único criterio
    #
    # REVISAR: con "or", la densidad de bordes de las propias pistas y
    # componentes puede superar 0.04 sin que haya pegamento, produciendo
    # falsos OK. Probablemente quieras "and".
    "decision_mode": "or",
}

# step del PLC -> par de rangos HSV definidos en ROI_FILE
RECIPES = {
    110: (("lower_beige", "upper_beige"), ("lower_gray", "upper_gray")),
    120: (("lower_pink", "upper_pink"), ("lower_dark", "upper_dark")),
}
DEFAULT_RECIPE_STEP = 120


# --------------------------------------------------------------------------
# Carga cacheada del fichero de ROIs
# --------------------------------------------------------------------------

_cache = {"mtime": None, "data": None}
_cache_lock = threading.Lock()


def load_roi_config(force=False):
    """Devuelve el contenido de ROI_FILE, releyéndolo sólo si ha cambiado."""
    with _cache_lock:
        try:
            mtime = os.path.getmtime(ROI_FILE)
        except OSError:
            mtime = None

        if force or _cache["data"] is None or _cache["mtime"] != mtime:
            with open(ROI_FILE, "r", encoding="utf-8") as f:
                _cache["data"] = json.load(f)
            _cache["mtime"] = mtime

        return _cache["data"]


def get_param(cfg, name):
    value = cfg.get(name, DEFAULTS[name])
    return value if value is not None else DEFAULTS[name]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def clamp_roi(x1, y1, x2, y2, width, height):
    """
    Ordena, redondea y recorta un ROI a los límites de la imagen.
    Devuelve None si el resultado no tiene área.
    """
    try:
        x1, x2 = sorted((int(round(float(x1))), int(round(float(x2)))))
        y1, y2 = sorted((int(round(float(y1))), int(round(float(y2)))))
    except (TypeError, ValueError):
        return None

    x1 = max(0, min(x1, width))
    x2 = max(0, min(x2, width))
    y1 = max(0, min(y1, height))
    y2 = max(0, min(y2, height))

    if (x2 - x1) < 1 or (y2 - y1) < 1:
        return None
    return x1, y1, x2, y2


def build_mask(hsv_img, cfg, recipe):
    """Combina los dos rangos HSV de la receta y limpia el ruido."""
    (low_a, up_a), (low_b, up_b) = recipe

    faltan = [k for k in (low_a, up_a, low_b, up_b) if k not in cfg]
    if faltan:
        raise KeyError(f"Faltan rangos HSV en el ROI file: {', '.join(faltan)}")

    mask_a = cv2.inRange(hsv_img,
                         np.array(cfg[low_a], dtype=np.uint8),
                         np.array(cfg[up_a], dtype=np.uint8))
    mask_b = cv2.inRange(hsv_img,
                         np.array(cfg[low_b], dtype=np.uint8),
                         np.array(cfg[up_b], dtype=np.uint8))

    combined = cv2.bitwise_or(mask_a, mask_b)

    k = int(get_param(cfg, "morph_kernel"))
    if k > 1:
        kernel = np.ones((k, k), np.uint8)
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

    return combined


def decide(ratio, edge_density, ratio_th, edge_th, mode):
    """Aplica el criterio de aceptación configurado."""
    ratio_ok = ratio > ratio_th
    edge_ok = edge_density > edge_th

    if mode == "and":
        return ratio_ok and edge_ok
    if mode == "ratio":
        return ratio_ok
    if mode == "edge":
        return edge_ok
    return ratio_ok or edge_ok      # "or" = comportamiento original


def _valid_rois(coords_array):
    """
    Filtra las entradas que realmente son un ROI de cuatro números.

    Evita el crash del 'for name, (x1,y1,x2,y2) in ...' cuando el diccionario
    contiene claves auxiliares como Components_List.
    """
    rois = {}
    for name, value in coords_array.items():
        if isinstance(value, (list, tuple)) and len(value) == 4:
            rois[name] = value
        else:
            print(f"[hsv] Entrada ignorada (no es un ROI de 4 valores): {name}")
    return rois


# --------------------------------------------------------------------------
# Inspección
# --------------------------------------------------------------------------

def hsvInspection(img, coords_array, offset_x, offset_y, step, draw_labels=True):
    """
    Evalúa cada ROI y devuelve (result_count, results_info, img_aux).

      result_count : lista de 1 (OK) / 0 (FAIL), un elemento por ROI.
      results_info : dict name -> {ratio, texture, area_px, status}
      img_aux      : copia de la imagen con los ROIs dibujados.

    Un ROI que cae fuera de la imagen se marca FAIL, no se ignora: dar por
    buena una zona que no se ha podido medir es el peor fallo posible en
    inspección.
    """
    if img is None:
        raise ValueError("hsvInspection recibió una imagen vacía")

    cfg = load_roi_config()

    img_aux = img.copy()
    height, width = img.shape[:2]

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Si la cámara entrega mono8 convertido a BGR, la saturación es 0 y las
    # máscaras de color no encontrarán nada. Merece la pena avisar.
    if hsv[:, :, 1].max() == 0:
        print("[hsv] AVISO: la imagen no tiene color (saturación 0). "
              "Revisa el pixel format de la cámara.")

    recipe = RECIPES.get(step)
    if recipe is None:
        print(f"[hsv] AVISO: step {step} desconocido, usando la receta "
              f"por defecto ({DEFAULT_RECIPE_STEP})")
        recipe = RECIPES[DEFAULT_RECIPE_STEP]

    mask_combined = build_mask(hsv, cfg, recipe)
    edges = cv2.Canny(gray,
                      int(get_param(cfg, "canny_low")),
                      int(get_param(cfg, "canny_high")))

    ratio_th = float(get_param(cfg, "ratio_threshold"))
    edge_th = float(get_param(cfg, "edge_threshold"))
    mode = str(get_param(cfg, "decision_mode")).lower()

    results_info = {}
    result_count = []

    for name, (x1, y1, x2, y2) in _valid_rois(coords_array).items():
        box = clamp_roi(x1 + offset_x, y1 + offset_y,
                        x2 + offset_x, y2 + offset_y, width, height)

        if box is None:
            print(f"[hsv] ROI '{name}' fuera de la imagen tras aplicar el "
                  f"offset ({offset_x}, {offset_y}) -> FAIL")
            results_info[name] = {"ratio": 0.0, "texture": 0.0,
                                  "area_px": 0, "status": "FAIL",
                                  "reason": "ROI fuera de la imagen"}
            result_count.append(0)
            continue

        rx1, ry1, rx2, ry2 = box
        roi_mask = mask_combined[ry1:ry2, rx1:rx2]
        roi_edges = edges[ry1:ry2, rx1:rx2]

        area_total = roi_mask.size
        area_roi = (rx2 - rx1) * (ry2 - ry1)    # antes: cv2.contourArea(...)
        area_glue = cv2.countNonZero(roi_mask)

        ratio = area_glue / area_total
        edge_density = np.count_nonzero(roi_edges) / roi_edges.size

        passed = decide(ratio, edge_density, ratio_th, edge_th, mode)
        status = "OK" if passed else "FAIL"
        color = (0, 255, 0) if passed else (0, 0, 255)

        cv2.rectangle(img_aux, (rx1, ry1), (rx2, ry2), color, 8)
        if draw_labels:
            cv2.putText(img_aux, f"{name} {ratio:.2f}", (rx1, max(ry1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3, cv2.LINE_AA)

        results_info[name] = {
            "ratio": ratio,
            "texture": edge_density,
            "area_px": area_roi,
            "status": status,
        }
        result_count.append(1 if passed else 0)

    for roi, info in results_info.items():
        print(f"Zona: {roi} | ratio={info['ratio']:.4f} "
              f"| textura={info['texture']:.4f} "
              f"| area={info['area_px']} px | {info['status']}")

    if not result_count:
        print("[hsv] AVISO: no se evaluó ningún ROI")

    return result_count, results_info, img_aux
