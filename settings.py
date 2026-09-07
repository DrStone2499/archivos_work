"""Constantes de codigo. Lo que el tecnico puede tocar vive en config.json."""

APP_NAME = "Re-etiquetado de cajas"
VERSION = "1.0.0"

HOST = "127.0.0.1"
PORT = 5678

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900

DB_PATH = "data/relabels.db"
CROPS_DIR = "data/crops"

# Campos del formulario de re-etiquetado.
# key -> (etiqueta visible, patron regex para autocompletar desde el OCR)
FIELDS = [
    {"key": "part_number", "label": "No. de parte", "pattern": r"\b[A-Z0-9]{4,6}-[A-Z0-9]{3,8}\b", "required": True},
    {"key": "lot",         "label": "Lote",         "pattern": r"(?:LOT|LOTE)[:\s]*([A-Z0-9\-]{4,})", "required": True},
    {"key": "quantity",    "label": "Cantidad",     "pattern": r"(?:QTY|CANT|PZ)[:\s]*(\d{1,6})", "required": True},
    {"key": "supplier",    "label": "Proveedor",    "pattern": r"(?:PROV|SUPPLIER)[:\s]*([A-Z0-9 \.]{3,})", "required": False},
    {"key": "date_code",   "label": "Fecha",        "pattern": r"\b(\d{2}[/-]\d{2}[/-]\d{2,4})\b", "required": False},
]

SSE_RETRY_MS = 2000
