# PyInstaller: pyinstaller build.spec --noconfirm
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("models", "models"),
    ("zpl", "zpl"),
    ("config.json", "."),
]
datas += collect_data_files("ultralytics")
datas += collect_data_files("easyocr")

hiddenimports = [
    "flask", "webview", "cv2", "numpy",
    "resources.camera_lib", "resources.detector_lib", "resources.ocr_lib",
    "resources.printer_lib", "resources.storage_lib", "resources.pipeline",
]
hiddenimports += collect_submodules("ultralytics")
hiddenimports += collect_submodules("easyocr")
# Descomenta si usas Basler:
# hiddenimports += collect_submodules("pypylon")

a = Analysis(["main.py"], pathex=["."], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
             excludes=["matplotlib", "tkinter", "PyQt5", "pandas"])
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Reetiquetado",
          console=False, icon=None)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Reetiquetado")
