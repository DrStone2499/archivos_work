"""Capa de camara. Misma interfaz para webcam USB y Basler (pypylon)."""
import threading
import time

import cv2
import numpy as np


class CameraError(RuntimeError):
    pass


class BaseCamera:
    def open(self):  raise NotImplementedError
    def read(self) -> np.ndarray: raise NotImplementedError
    def close(self): raise NotImplementedError

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


class UsbCamera(BaseCamera):
    def __init__(self, cfg: dict):
        self.index = cfg.get("index", 0)
        self.width = cfg.get("width", 1920)
        self.height = cfg.get("height", 1080)
        self.cap = None

    def open(self):
        self.cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise CameraError(f"No abre la camara USB indice {self.index}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            raise CameraError("Frame vacio de la camara USB")
        return frame

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class BaslerCamera(BaseCamera):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cam = None
        self.converter = None

    def open(self):
        from pypylon import pylon  # import tardio: solo si se usa Basler

        factory = pylon.TlFactory.GetInstance()
        serial = self.cfg.get("serial") or ""
        if serial:
            devices = [d for d in factory.EnumerateDevices() if d.GetSerialNumber() == serial]
            if not devices:
                raise CameraError(f"No se encontro la Basler con serie {serial}")
            self.cam = pylon.InstantCamera(factory.CreateDevice(devices[0]))
        else:
            self.cam = pylon.InstantCamera(factory.CreateFirstDevice())

        self.cam.Open()
        try:
            self.cam.ExposureTime.SetValue(float(self.cfg.get("exposure_us", 8000)))
        except Exception:
            pass  # algunos modelos usan ExposureTimeAbs

        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned
        self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    def read(self):
        from pypylon import pylon

        result = self.cam.RetrieveResult(2000, pylon.TimeoutHandling_ThrowException)
        try:
            if not result.GrabSucceeded():
                raise CameraError("Grab fallido en la Basler")
            return self.converter.Convert(result).GetArray()
        finally:
            result.Release()

    def close(self):
        if self.cam is not None:
            if self.cam.IsGrabbing():
                self.cam.StopGrabbing()
            self.cam.Close()
            self.cam = None


class FileCamera(BaseCamera):
    """Para probar la UI sin hardware: reproduce un video o una imagen en bucle."""

    def __init__(self, cfg: dict):
        self.source = cfg.get("source", "")
        self.cap = None
        self.still = None

    def open(self):
        if self.source.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            self.still = cv2.imread(self.source)
            if self.still is None:
                raise CameraError(f"No se pudo leer {self.source}")
        else:
            self.cap = cv2.VideoCapture(self.source)
            if not self.cap.isOpened():
                raise CameraError(f"No se pudo abrir {self.source}")

    def read(self):
        if self.still is not None:
            time.sleep(0.03)
            return self.still.copy()
        ok, frame = self.cap.read()
        if not ok:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        if not ok:
            raise CameraError("Video sin frames")
        return frame

    def close(self):
        if self.cap is not None:
            self.cap.release()


_BACKENDS = {"usb": UsbCamera, "basler": BaslerCamera, "file": FileCamera}


def build_camera(cfg: dict) -> BaseCamera:
    backend = cfg.get("backend", "usb").lower()
    if backend not in _BACKENDS:
        raise CameraError(f"Backend de camara desconocido: {backend}")
    return _BACKENDS[backend](cfg)


class CameraStream:
    """Hilo de captura. Siempre guarda el ultimo frame; nadie se queda esperando IO."""

    def __init__(self, cfg: dict):
        self.camera = build_camera(cfg)
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.error = None

    def start(self):
        self.camera.open()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                frame = self.camera.read()
                with self._lock:
                    self._frame = frame
                self.error = None
            except Exception as exc:
                self.error = str(exc)
                time.sleep(0.5)

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.camera.close()
