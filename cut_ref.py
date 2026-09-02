"""
cut_ref.py - Localiza la referencia (fiducial) y lanza la inspección HSV.

Correcciones sobre la versión original:

  1. Si GetOffset lanzaba una excepción, el 'except' sólo imprimía y
     offset_x / offset_y nunca se asignaban -> NameError en la línea
     siguiente. Ahora hay una política explícita de qué hacer cuando no se
     encuentra la referencia.
  2. El ROI file se cargaba una sola vez al importar el módulo: había que
     reiniciar la aplicación para que un cambio de ROI surtiera efecto.
     Ahora se lee a través del caché por mtime de hsv.load_roi_config().
  3. 'number' no se validaba contra el tamaño de lbls / ref_paths.
  4. No se comprobaba que la imagen fuese válida.
"""

import cv2

from hsv import hsvInspection, load_roi_config
from static.config.settings import ROI_FILE, REF_PATH1, REF_PATH2
from resources.getOffset import *
from resources.TimInspect import *


LABELS = ["Top_1", "Top_2"]
REF_PATHS = [REF_PATH1, REF_PATH2]

# Si no se localiza la referencia, los ROIs quedan desalineados y cualquier
# medición es inválida. Con True la pieza se marca NG; con False se inspecciona
# con offset (0, 0), que es lo que hacía la versión original cuando GetOffset
# funcionaba pero devolvía basura.        # REVISAR
FAIL_ON_MISSING_REFERENCE = True


def get_offset(img, number, cfg):
    """
    Devuelve (offset_x, offset_y, encontrado).

    Nunca lanza: el llamador decide qué hacer si no hay referencia.
    """
    try:
        offset_x, offset_y = GetOffset(
            img,
            REF_PATHS[number],
            cfg["Ref_SearchZones"][number],
            cfg["Ref_Coords"][number],
        )
        return int(offset_x), int(offset_y), True
    except Exception as exc:
        print(f"[cut_ref] No se pudo localizar la referencia de "
              f"{LABELS[number]}: {exc}")
        return 0, 0, False


def timFunction(img, number, step):
    """
    Ejecuta la inspección completa de una cámara.

    Devuelve (result_count, result_info, img_aux), la misma firma que la
    versión original para no romper app.py.
    """
    if img is None:
        raise ValueError("timFunction recibió una imagen vacía")

    if not 0 <= number < len(LABELS):
        raise IndexError(f"Índice de cámara fuera de rango: {number}")

    cfg = load_roi_config()

    label = LABELS[number]
    if label not in cfg:
        raise KeyError(f"El ROI file no contiene la sección '{label}'")

    offset_x, offset_y, found = get_offset(img, number, cfg)
    print(f"[cut_ref] {label} offset=({offset_x}, {offset_y}) "
          f"referencia={'OK' if found else 'NO ENCONTRADA'}")

    if not found and FAIL_ON_MISSING_REFERENCE:
        # Se marca la pieza como NG sin inspeccionar: medir sobre ROIs
        # desalineados daría un resultado sin ningún valor.
        img_aux = img.copy()
        cv2.putText(img_aux, "REFERENCE NOT FOUND", (40, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 255), 4, cv2.LINE_AA)
        result_info = {
            "_reference": {
                "ratio": 0.0,
                "texture": 0.0,
                "area_px": 0,
                "status": "FAIL",
                "reason": "Referencia no encontrada",
            }
        }
        return [0], result_info, img_aux

    coords_array = cfg[label]
    return hsvInspection(img, coords_array, offset_x, offset_y, step)


# Compatibilidad con el nombre antiguo de las constantes del módulo.
lbls = LABELS
ref_paths = REF_PATHS
