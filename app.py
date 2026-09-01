"""
TIM INSPECTION - Aplicación de inspección industrial.

Refactor sobre la versión original. Cambios principales:

  1. GUI thread-safe: ningún hilo secundario toca widgets directamente.
     Todo pasa por _ui() -> root.after(0, ...). Los popups usan
     popup_choice(), que bloquea el hilo trabajador pero ejecuta el
     diálogo en el hilo principal.
  2. Sin recursión: los reintentos usan 'continue' dentro del bucle.
  3. Flujo del ciclo corregido: SIEMPRE se evalúan las dos cámaras
     antes de decidir OK/NG, y el bucle no termina tras una pieza.
  4. writeLog() con firma coherente con sus llamadas y creación real
     de directorios.
  5. open_camera() devuelve siempre una tupla (cam, label).
  6. work_photo() libera el buffer en un finally y soporta mono8.
  7. Botones Start/Restart/Stop con estados reales.

NOTA: revisa las constantes marcadas con  # REVISAR  antes de desplegar.
"""

import datetime
import json
import os
import shutil
import threading
import time
from ctypes import POINTER, byref, c_bool, c_ubyte, cast, memmove, memset, sizeof

import cv2
import numpy as np
from configparser import RawConfigParser
from tkinter import messagebox

from resources.PLC_Lib import *
from resources.Camera_Lib import *
from resources.DatalogicLib import *
from resources.sfis_module import *
from resources.widgets import *
from resources.hikvision_connection import *
from static.config.settings import CONFIG_FILE, MEMORY_FILE, PATH_LOG
from cut_ref import *

from MvCameraControl_class import *


# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

STEP_TRIGGER = 110          # valor de la memoria D que dispara un ciclo
STEP_CAMERA_2 = 120         # "step" que se pasa a timFunction para la cámara 2
POLL_INTERVAL = 0.2         # segundos entre lecturas del PLC
LIGHT_SETTLE = 0.1          # espera tras encender la iluminación
DISK_THRESHOLD = 99         # % de uso a partir del cual se avisa
IMAGE_SIZE = (490, 500)     # tamaño de preview en la GUI

MODE = "production"         # 'production' | 'develop'

# Raíz de los logs de imagen. La versión original mezclaba PATH_LOG con
# os.getcwd()/log; aquí se unifica en PATH_LOG.   # REVISAR
LOG_ROOT = PATH_LOG


# --------------------------------------------------------------------------
# Estado global
# --------------------------------------------------------------------------

var_setUp = [0, 0, 0, 0]        # PLC, SFIS, cam1, cam2
myPlc = None
cam1 = None
cam2 = None
total = 0
current_isn = ""

start_process = threading.Event()   # el operador pulsó Start
retry_val = threading.Event()       # el operador pulsó Restart
ok2run = threading.Event()          # setup completo
stop_event = threading.Event()      # el operador pulsó Stop

plc_lock = threading.Lock()         # el PLC no es reentrante
camera_lock = threading.Lock()      # evita capturas simultáneas
counter_lock = threading.Lock()

_ui_root = None                     # widget usado para .after()

config = RawConfigParser(allow_no_value=True)
with open("resources/config.ini", "r", encoding="utf-8-sig") as _fp:
    config.read_file(_fp)


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_memorys():
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(payload):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)


data = load_config()


# --------------------------------------------------------------------------
# Fecha / hora
#
# En el original year/month/day/hour/minute eran globales que sólo se
# refrescaban en dos sitios, así que casi todos los mensajes de log
# mostraban la hora de arranque del programa.
# --------------------------------------------------------------------------

def now_parts():
    n = datetime.datetime.now()
    return (f"{n.year}", f"{n.month:02}", f"{n.day:02}",
            f"{n.hour:02}", f"{n.minute:02}")


def stamp():
    """Marca de tiempo actual para los mensajes de log."""
    n = datetime.datetime.now()
    return f"{n.hour:02}:{n.minute:02}:{n.second:02}"


# --------------------------------------------------------------------------
# Puente hilo trabajador -> hilo de la GUI
# --------------------------------------------------------------------------

def _is_main_thread():
    return threading.current_thread() is threading.main_thread()


def _ui(fn, *args, **kwargs):
    """Programa fn() en el hilo principal de Tk. Seguro desde cualquier hilo."""
    if _ui_root is None:
        return
    if _is_main_thread():
        try:
            fn(*args, **kwargs)
        except Exception as exc:
            print(f"[ui] {exc}")
        return
    try:
        _ui_root.after(0, lambda: _safe_call(fn, *args, **kwargs))
    except Exception as exc:
        print(f"[ui] {exc}")


def _safe_call(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        print(f"[ui] {exc}")


def set_widget(widget, **kwargs):
    """configure() defensivo: una opción no soportada no debe tumbar la app."""
    def _apply():
        try:
            widget.configure(**kwargs)
        except Exception as exc:
            print(f"[widget] {exc}")
    _ui(_apply)


def add_log_message(message):
    """Añade una línea a la consola. Seguro desde cualquier hilo."""
    text = f"--- {stamp()} --- {message}"
    print(text)

    def _append():
        consoleLog.configure(state="normal")
        consoleLog.insert("end", text + "\n")
        consoleLog.see("end")
        consoleLog.configure(state="disabled")

    _ui(_append)


def clear_log_box():
    def _clear():
        consoleLog.configure(state="normal")
        consoleLog.delete("1.0", "end")
        consoleLog.configure(state="disabled")
    _ui(_clear)


def popup_choice(title, message, options):
    """
    Muestra un diálogo y devuelve el índice (0-based) de la opción elegida.

    addPopUp devuelve un bool con 2 opciones y una tupla con 3; esta función
    normaliza ambos casos para que el resto del código no dependa de ello.
    """
    result = {}
    done = threading.Event()

    def _show():
        try:
            result["value"] = app.addPopUp(title, message, options)
        except Exception as exc:
            result["error"] = exc
        finally:
            done.set()

    if _is_main_thread():
        _show()
    else:
        _ui(_show)
        done.wait()

    if "error" in result:
        add_log_message(f"popup error: {result['error']}")
        return 0

    value = result.get("value")
    if isinstance(value, (tuple, list)):
        for i, flag in enumerate(value):
            if flag:
                return i + 1
        return 0
    return 1 if value else 0


# --------------------------------------------------------------------------
# Escritura de resultados
# --------------------------------------------------------------------------

def writeLog(base_path, img, isn, index, img_aux):
    """
    Guarda la imagen original y la procesada.

    Original: la firma era (img, isn, n, imgaux, result) pero se llamaba con
    (real_log, img, isn, n, img_aux), así que todos los argumentos estaban
    desplazados una posición. Además la comprobación de existencia usaba
    os.path.join en lugar de os.path.exists y nunca creaba la carpeta.
    """
    isn_clean = str(isn).replace(":", "").replace("/", "_")
    target = os.path.join(base_path, isn_clean)
    os.makedirs(target, exist_ok=True)

    names = [f"{isn_clean}_Top_1.jpg", f"{isn_clean}_Top_2.jpg"]
    name = names[index] if index < len(names) else f"{isn_clean}_Top_{index + 1}.jpg"

    if img is not None and not cv2.imwrite(os.path.join(target, name), img):
        add_log_message(f"No se pudo escribir {name}")
    if img_aux is not None:
        cv2.imwrite(os.path.join(target, f"Result_{index}.jpg"), img_aux)

    return target


def writeLogSFIS(base_path, txt, isn):
    isn_clean = str(isn).replace(":", "").replace("/", "_")
    target = os.path.join(base_path, isn_clean)
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, "result.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    return target


def build_sfis_payload(passed):
    status = 1 if passed else 0
    return ("TEST,TSTATUS,TVALUE,UCL,LCL\n"
            f"AOItest,{status},{status},0,2")


def verificar_disco(ruta=None, umbral=DISK_THRESHOLD):
    """
    Devuelve True si hay espacio suficiente, False si el operador cancela.

    Original: ambas ramas del if hacían 'return verificar_disco()', con lo
    que la función nunca podía terminar.
    """
    if ruta is None:
        ruta = os.path.splitdrive(os.path.abspath(LOG_ROOT))[0] or os.path.abspath(LOG_ROOT)

    while not stop_event.is_set():
        try:
            total_b, usado, _ = shutil.disk_usage(ruta)
        except OSError as exc:
            add_log_message(f"No se pudo leer el disco: {exc}")
            return False

        porcentaje = (usado / total_b) * 100
        if porcentaje < umbral:
            return True

        add_log_message(f"ALERTA: disco al {porcentaje:.2f}%")
        choice = popup_choice(
            "There is not enough space on the disk",
            "CLEAN THE LOG AND CLICK RETRY, OR CANCEL TO SKIP THIS PART",
            ["Cancel", "Retry"],
        )
        if choice == 0:
            add_log_message("Operación cancelada por falta de espacio")
            return False

    return False


# --------------------------------------------------------------------------
# Cámaras (SDK MVS)
# --------------------------------------------------------------------------

def _c_string(buffer):
    chars = []
    for byte in buffer:
        if byte == 0:
            break
        chars.append(chr(byte))
    return "".join(chars)


def _device_label(info):
    """IP para GigE, número de serie para USB3."""
    if info.nTLayerType == MV_GIGE_DEVICE:
        raw = info.SpecialInfo.stGigEInfo.nCurrentIp
        return "%d.%d.%d.%d" % ((raw >> 24) & 0xFF, (raw >> 16) & 0xFF,
                                (raw >> 8) & 0xFF, raw & 0xFF)
    if info.nTLayerType == MV_USB_DEVICE:
        return _c_string(info.SpecialInfo.stUsb3VInfo.chSerialNumber)
    return "unknown"


def open_camera(index):
    """
    Abre la cámara en la posición 'index' de la enumeración.

    Devuelve SIEMPRE una tupla (cam, label); (None, None) si falla.
    Original: unos caminos devolvían None suelto y otros None, None, así que
    'cam1, ip = open_camera(0)' podía lanzar TypeError al desempaquetar. La
    IP además se tomaba del último dispositivo iterado, no del seleccionado.
    """
    device_list = MV_CC_DEVICE_INFO_LIST()
    layer = MV_GIGE_DEVICE | MV_USB_DEVICE

    ret = MvCamera.MV_CC_EnumDevices(layer, device_list)
    if ret != 0:
        add_log_message(f"enum devices fail [0x{ret:x}]")
        return None, None

    if device_list.nDeviceNum == 0:
        add_log_message("No se encontraron cámaras")
        return None, None

    if index >= device_list.nDeviceNum:
        add_log_message(f"Cámara {index} no disponible "
                        f"({device_list.nDeviceNum} detectadas)")
        return None, None

    info = cast(device_list.pDeviceInfo[index], POINTER(MV_CC_DEVICE_INFO)).contents
    label = _device_label(info)

    cam = MvCamera()
    ret = cam.MV_CC_CreateHandle(info)
    if ret != 0:
        add_log_message(f"create handle fail [0x{ret:x}]")
        return None, None

    ret = cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
    if ret != 0:
        add_log_message(f"open device fail [0x{ret:x}]")
        cam.MV_CC_DestroyHandle()
        return None, None

    if info.nTLayerType == MV_GIGE_DEVICE:
        packet_size = cam.MV_CC_GetOptimalPacketSize()
        if int(packet_size) > 0:
            ret = cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size)
            if ret != 0:
                add_log_message(f"Warning: set packet size fail [0x{ret:x}]")
        else:
            add_log_message("Warning: no se pudo obtener el packet size óptimo")

    stBool = c_bool(False)
    cam.MV_CC_GetBoolValue("AcquisitionFrameRateEnable", stBool)
    cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)

    ret = cam.MV_CC_StartGrabbing()
    if ret != 0:
        add_log_message(f"start grabbing fail [0x{ret:x}]")
        close_camera(cam)
        return None, None

    return cam, label


def close_camera(cam):
    if cam is None:
        return
    try:
        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
    except Exception as exc:
        print(f"[camera] {exc}")


def work_photo(cam, timeout_ms=1000):
    """
    Captura un frame y lo devuelve en BGR, o None si falla.

    El buffer se libera en un finally: en el original, cualquier excepción
    durante el reshape dejaba el buffer sin liberar y acababa agotando la
    memoria de la cámara.
    """
    if cam is None:
        return None

    frame_out = MV_FRAME_OUT()
    memset(byref(frame_out), 0, sizeof(frame_out))

    ret = cam.MV_CC_GetImageBuffer(frame_out, timeout_ms)
    if ret != 0 or not frame_out.pBufAddr:
        add_log_message(f"no data [0x{ret:x}]")
        return None

    try:
        info = frame_out.stFrameInfo
        buf = (c_ubyte * info.nFrameLen)()
        memmove(buf, frame_out.pBufAddr, info.nFrameLen)
        raw = np.frombuffer(buf, dtype=np.uint8)

        pixels = info.nWidth * info.nHeight

        if info.nFrameLen >= pixels * 2:
            packed = raw[:pixels * 2].reshape((info.nHeight, info.nWidth, 2))
            return cv2.cvtColor(packed, cv2.COLOR_YUV2BGR_YUYV)

        if info.nFrameLen >= pixels:
            mono = raw[:pixels].reshape((info.nHeight, info.nWidth))
            return cv2.cvtColor(mono, cv2.COLOR_GRAY2BGR)

        add_log_message(f"Frame incompleto: {info.nFrameLen} bytes "
                        f"para {info.nWidth}x{info.nHeight}")
        return None

    except Exception as exc:
        add_log_message(f"Error decodificando frame: {exc}")
        return None
    finally:
        cam.MV_CC_FreeImageBuffer(frame_out)


def capture(cam):
    with camera_lock:
        return work_photo(cam)


# --------------------------------------------------------------------------
# GUI: actualizaciones
# --------------------------------------------------------------------------

def UpdateImage(img, camera):
    """Muestra un frame en el panel correspondiente. Seguro desde cualquier hilo."""
    if img is None:
        return

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, IMAGE_SIZE)
    pil = Image.fromarray(rgb)

    def _apply():
        ctk_img = ctk.CTkImage(pil, size=IMAGE_SIZE)
        if camera == 0:
            lblCameraNumber.configure(text="Camera 1")
            img_gui.configure(image=ctk_img)
            img_gui._img_ref = ctk_img      # evita que el GC se lo lleve
        else:
            lblCameraNumber.configure(text="Camera 2")
            img_gui2.configure(image=ctk_img)
            img_gui2._img_ref = ctk_img

    _ui(_apply)


def set_led(led, ok):
    set_widget(led, fg_color="green" if ok else "red")


def bump_total():
    global total
    with counter_lock:
        total += 1
        value = total
    set_widget(lblTotal, text=f"Total:{value}")


def show_isn(isn):
    global current_isn
    current_isn = isn
    set_widget(lblISN, text=f"ISN:{isn}")


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------

def setInfo():
    """Rellena la pestaña de ajustes con la configuración guardada."""
    if not data:
        return

    devices = data.get("devices", {})
    entryUser.insert(0, str(data.get("user", "")))
    entryIpPlc.insert(0, str(devices.get("plc", {}).get("ip", "")))
    entryPortPlc.insert(0, str(devices.get("plc", {}).get("port", "")))
    entryIpCam.insert(0, str(devices.get("cam1", {}).get("ip", "")))
    entryIpCam2.insert(0, str(devices.get("cam2", {}).get("ip", "")))
    entryIpScanner.insert(0, str(devices.get("scanner", {}).get("ip", "")))
    entryPortScanner.insert(0, str(devices.get("scanner", {}).get("port", "")))

    # El original activaba switchActivateQuestions dos veces y nunca
    # restauraba switchActivateQuestionPass.
    toggles = (
        (switchActivateQuestions, data.get("question")),
        (switchActivateQuestionPass, data.get("question_pass")),
        (switchActivateSfi, data.get("sfis")),
        (switchActivateScanner, data.get("scanner")),
    )
    for widget, value in toggles:
        if value == 1:
            widget.select()
        else:
            widget.deselect()


def userLogin():
    """Valida credenciales y guarda la configuración."""
    global data

    user = entryUser.get()
    password = entryPass.get()

    # NOTA: las credenciales se comparan en claro contra el JSON. Si esto
    # llega a producción, conviene guardar un hash.   # REVISAR
    if data.get("user") != user or data.get("password") != password:
        messagebox.showerror("Error", "User or password wrong.")
        return

    campos = {
        "IP PLC": entryIpPlc.get(),
        "PORT PLC": entryPortPlc.get(),
        "IP Camera 1": entryIpCam.get(),
        "IP Camera 2": entryIpCam2.get(),
    }
    faltantes = [nombre for nombre, valor in campos.items() if not valor.strip()]
    if faltantes:
        messagebox.showinfo("Error", "Missing some data: " + ", ".join(faltantes))
        return

    try:
        plc_port = int(entryPortPlc.get())
        scanner_port = int(entryPortScanner.get() or 0)
    except ValueError:
        messagebox.showerror("Error", "Los puertos deben ser números enteros.")
        return

    new_data = {
        "user": data["user"],
        "password": data["password"],
        "question": switchActivateQuestions.get(),
        "question_pass": switchActivateQuestionPass.get(),
        "sfis": switchActivateSfi.get(),
        "scanner": switchActivateScanner.get(),
        "devices": {
            "cam1": {"ip": entryIpCam.get()},
            "cam2": {"ip": entryIpCam2.get()},
            "plc": {"ip": entryIpPlc.get(), "port": plc_port},
            "scanner": {"ip": entryIpScanner.get(), "port": scanner_port},
        },
    }

    try:
        save_config(new_data)
    except IOError as exc:
        messagebox.showerror("Error", f"No se pudo guardar: {exc}")
        add_log_message(f"Error guardando configuración: {exc}")
        return

    data = new_data
    devices = new_data["devices"]

    # Los f-strings anidados con comillas dobles del original
    # (f"IP:{new_data["devices"]...}") sólo son válidos en Python 3.12+.
    set_widget(lblIpInfoCamera1, text="IP:{}".format(devices["cam1"]["ip"]))
    set_widget(lblIpInfoCamera2, text="IP:{}".format(devices["cam2"]["ip"]))
    set_widget(lblIpInfoPlc, text="IP:{}".format(devices["plc"]["ip"]))
    set_widget(lblPortInfoPlc, text="PORT:{}".format(devices["plc"]["port"]))

    add_log_message("Configuración guardada")


# --------------------------------------------------------------------------
# Foto manual
# --------------------------------------------------------------------------

def takePhoto():
    """
    Captura manual desde la GUI.

    El original llamaba a cam.takePicture()/getImg() (API de Basler) sobre
    handles del SDK de MVS, y además disparaba la captura dos veces por el
    print(). Aquí se usa work_photo(), igual que el ciclo principal.
    """
    if start_process.is_set() and not stop_event.is_set():
        messagebox.showinfo("Info", "Detén el proceso antes de tomar una foto manual.")
        return

    choice = popup_choice("TAKE A PHOTO",
                          "Which camera wanted to take a photo?",
                          ["Camera 1", "Camera 2"])
    index = choice
    cam = cam2 if index == 1 else cam1

    if cam is None:
        add_log_message(f"Camera {index + 1} no disponible")
        return

    add_log_message(f"Captura manual - Camera {index + 1}")
    img = capture(cam)
    if img is None:
        add_log_message(f"Camera {index + 1}: sin imagen")
        return
    UpdateImage(img, index)


# --------------------------------------------------------------------------
# Setup de dispositivos
# --------------------------------------------------------------------------

def connect_plc(plc_cfg):
    global myPlc
    if MODE == "develop":
        add_log_message("PLC connected (develop mode)")
        set_led(ledPlc, True)
        return True

    try:
        myPlc = SLMP_PLC(plc_cfg["ip"], int(plc_cfg["port"]))
    except Exception as exc:
        myPlc = None
        add_log_message(f"PLC FAIL connection: {exc}")
        set_led(ledPlc, False)
        return False

    if myPlc.client is None:
        add_log_message("PLC FAIL connection")
        set_led(ledPlc, False)
        return False

    add_log_message("PLC connected")
    set_led(ledPlc, True)
    return True


def connect_sfis(sfis_enabled):
    if MODE == "develop":
        add_log_message("SFIS connected (develop mode)")
        set_led(ledSfis, True)
        return True

    if sfis_enabled != 1:
        add_log_message("SFIS not enabled")
        set_led(ledSfis, False)
        return True     # no bloquea el arranque

    op_id = config.get("SFIS", "op_id")
    device = config.get("SFIS", "device")
    try:
        logout(op_id, device=device)
        sfis_message = login(op_id, device=device)
    except Exception as exc:
        add_log_message(f"SFIS error: {exc}")
        set_led(ledSfis, False)
        return False

    if int(sfis_message[0]) == 1:
        add_log_message("SFIS connected")
        set_led(ledSfis, True)
        return True

    add_log_message(f"SFIS login rechazado: {sfis_message}")
    set_led(ledSfis, False)
    return False


def connect_camera(index, led, label_widget):
    if MODE == "develop":
        add_log_message(f"Camera {index + 1} connected (develop mode)")
        set_led(led, True)
        return True, None

    cam, ip = open_camera(index)
    if cam is None:
        add_log_message(f"Camera {index + 1} not connected")
        set_led(led, False)
        return False, None

    add_log_message(f"Camera {index + 1} connected")
    set_widget(label_widget, text=f"IP:{ip}")
    set_led(led, True)
    return True, cam


def setUp():
    """Hilo de arranque: conecta dispositivos y luego lanza el ciclo."""
    global cam1, cam2

    datos = load_config()
    plc_cfg = datos["devices"]["plc"]
    sfis_enabled = datos.get("sfis", 0)

    while not stop_event.is_set():
        if var_setUp[0] == 0 and connect_plc(plc_cfg):
            var_setUp[0] = 1

        if var_setUp[1] == 0 and connect_sfis(sfis_enabled):
            var_setUp[1] = 1

        if var_setUp[2] == 0:
            ok, cam = connect_camera(0, ledCamera1, lblIpInfoCamera1)
            if ok:
                var_setUp[2] = 1
                cam1 = cam

        if var_setUp[3] == 0:
            ok, cam = connect_camera(1, ledCamera2, lblIpInfoCamera2)
            if ok:
                var_setUp[3] = 1
                cam2 = cam

        if 0 not in var_setUp:
            break

        add_log_message("Please press Restart to try again")
        set_widget(buttonRestart, state="normal")
        retry_val.wait()
        retry_val.clear()

    if stop_event.is_set():
        return

    add_log_message("Program ready to start")
    ok2run.set()
    set_widget(buttonStart, state="normal")

    start_process.wait()
    if stop_event.is_set():
        return

    run_main_loop()


# --------------------------------------------------------------------------
# Ciclo principal
# --------------------------------------------------------------------------

def read_isn(cfg, scanner_cfg):
    if cfg.get("scanner") == 1:
        # Original: se leía data["ip_scanner"] / data["port_scanner"], claves
        # que no existen en el JSON, y luego readQR se llamaba otra vez más
        # abajo, provocando un doble escaneo por ciclo.
        return readQR(scanner_cfg["ip"], int(scanner_cfg["port"]))

    year, month, day, hour, minute = now_parts()
    return f"{hour}{minute}_{month}_{day}_{year}"


def check_sfis_route(isn):
    """Devuelve (ok, mensaje)."""
    op_id = config.get("SFIS", "op_id")
    device = config.get("SFIS", "device")
    try:
        logout(op_id, device=device)
        login(op_id, device=device)
        message = check_route(isn, device=device)
    except Exception as exc:
        add_log_message(f"CHECK ROUTE error: {exc}")
        return False, [0]
    return int(message[0]) == 1, message


def report_to_sfis(isn, passed, payload):
    device = config.get("SFIS", "device")
    error_code = "" if passed else config.get("SFIS", "sfis_error")
    try:
        # Original: 'sfis_error if final_result == 0 else ""' comparaba una
        # lista contra 0, así que nunca se enviaba el código de error.
        send_result(isn, device, error_code, config.get("SFIS", "tsp"), payload)
        logout(config.get("SFIS", "op_id"), device=device)
    except Exception as exc:
        add_log_message(f"SFIS send_result error: {exc}")


def evaluate_result(result_count, titulo, mensaje):
    """
    Devuelve 'pass', 'fail' o 'retry' según el resultado y, si hace falta,
    la decisión del operador.
    """
    if 0 not in result_count:
        return "pass"

    choice = popup_choice(titulo, mensaje, ["NG", "OK", "RETRY"])
    if choice == 2:
        add_log_message("Operador: RETRY")
        return "retry"
    if choice == 1:
        add_log_message("Operador: OK forzado")
        return "pass"
    add_log_message("Operador: NG")
    return "fail"


def run_main_loop():
    """
    Bucle de producción.

    Diferencias clave frente al original:
      - Los 'return run_main_loop()' se sustituyen por 'continue' (antes era
        recursión y acababa en RecursionError).
      - Los 'break' de OK/NG se sustituyen por 'continue': antes el hilo
        terminaba tras procesar una sola pieza.
      - Los 'else: continue' hacían que, si la primera cámara pasaba, nunca
        se evaluara la segunda ni se escribiera el resultado OK. Ahora
        siempre se capturan y evalúan ambas antes de decidir.
      - La segunda captura usa cam2, no cam1.
    """
    global myPlc

    if MODE != "develop" and myPlc is None:
        add_log_message("PLC no disponible, no se puede iniciar el ciclo")
        return

    add_log_message("Ciclo de producción iniciado")

    while not stop_event.is_set():
        ok2run.wait()
        time.sleep(POLL_INTERVAL)

        try:
            dataMemory = load_memorys()
            cfg = load_config()
            scanner_cfg = cfg["devices"]["scanner"]
            sfis_enabled = cfg.get("sfis", 0)

            year, month, day, hour, minute = now_parts()
            log_path = os.path.join(LOG_ROOT, year, month, day)

            # --- disparo del PLC -------------------------------------
            if MODE != "develop":
                with plc_lock:
                    step = myPlc.read_Dmemory(dataMemory["step"])
                if not step or step[0] != STEP_TRIGGER:
                    continue
                step_value = step[0]
            else:
                step_value = STEP_TRIGGER

            # --- ISN --------------------------------------------------
            isn = read_isn(cfg, scanner_cfg)
            show_isn(isn)

            # --- ruta SFIS -------------------------------------------
            if sfis_enabled == 1 and cfg.get("scanner") == 1:
                isn = isn.replace("_", ":")
                route_ok, message = check_sfis_route(isn)
                if not route_ok:
                    add_log_message("Wrong route")
                    add_log_message(str(message))
                    popup_choice("Test",
                                 "Please press emergency stop and remove PCBA",
                                 ["Cancel", "Continue"])
                    continue

            # --- captura ---------------------------------------------
            if MODE != "develop":
                with plc_lock:
                    myPlc.active_Mmemory(dataMemory["light_source1"])
                    myPlc.active_Mmemory(dataMemory["light_source2"])
                time.sleep(LIGHT_SETTLE)

            try:
                if MODE != "develop":
                    img = capture(cam1)
                    time.sleep(LIGHT_SETTLE)
                    img2 = capture(cam2)      # antes: cam1
                else:
                    img = cv2.imread(input("path image 1 : "))
                    img2 = cv2.imread(input("path image 2 : "))
            finally:
                if MODE != "develop":
                    with plc_lock:
                        myPlc.desactive_Mmemory(dataMemory["light_source1"])
                        myPlc.desactive_Mmemory(dataMemory["light_source2"])

            # 'img == None' sobre un ndarray lanza el error de ambigüedad.
            if img is None:
                add_log_message("No photo from camera 1")
                continue
            if img2 is None:
                add_log_message("No photo from camera 2")
                continue

            # --- análisis ---------------------------------------------
            result_count, result_info, img_aux = timFunction(img, 0, step_value)
            UpdateImage(img_aux, 0)

            result_count2, result_info2, img_aux2 = timFunction(img2, 1, STEP_CAMERA_2)
            UpdateImage(img_aux2, 1)

            for name, values in result_info.items():
                print(name, values["status"])
            for name, values in result_info2.items():
                print(name, values["status"])

            # --- decisión ---------------------------------------------
            first = evaluate_result(result_count, "Test fail", "Test fail, retry?")
            if first == "retry":
                continue

            second = evaluate_result(result_count2, "Test 2 fail", "Test 2 fail, retry?")
            if second == "retry":
                continue

            passed = (first == "pass" and second == "pass")

            if not verificar_disco():
                add_log_message("Ciclo omitido por falta de espacio en disco")
                continue

            # --- escritura de resultados ------------------------------
            folder = os.path.join(log_path, "OK" if passed else "NG")
            writeLog(folder, img, isn, 0, img_aux)
            writeLog(folder, img2, isn, 1, img_aux2)

            payload = build_sfis_payload(passed)
            writeLogSFIS(folder, payload, isn)

            if sfis_enabled == 1:
                report_to_sfis(isn, passed, payload)

            if MODE != "develop":
                with plc_lock:
                    myPlc.active_Mmemory(dataMemory["OK" if passed else "NG"])

            add_log_message(f"{'OK' if passed else 'NG'} result written")
            bump_total()

        except Exception as exc:
            # Sin la pausa, un fallo persistente convertía esto en un bucle
            # que saturaba la CPU y el log.
            add_log_message(f"Error en el ciclo: {exc}")
            time.sleep(1)

    add_log_message("Ciclo de producción detenido")


# --------------------------------------------------------------------------
# Botones
# --------------------------------------------------------------------------

def startButton():
    if not ok2run.is_set():
        add_log_message("El setup aún no ha terminado")
        return
    if start_process.is_set():
        return

    add_log_message("Start pressed")
    stop_event.clear()
    start_process.set()
    set_widget(buttonStart, state="disabled")
    set_widget(buttonStop, state="normal")


def resetButton():
    """Reintenta la conexión de los dispositivos que fallaron."""
    if ok2run.is_set():
        add_log_message("El sistema ya está listo; Restart no es necesario")
        return

    add_log_message("Restarting")
    for i, led in enumerate((ledPlc, ledSfis, ledCamera1, ledCamera2)):
        if var_setUp[i] == 0:
            set_led(led, False)
    retry_val.set()


def stopButton():
    """Detiene el ciclo y libera las cámaras. Antes sólo hacía print('stop')."""
    add_log_message("Stop pressed")
    stop_event.set()
    ok2run.set()        # desbloquea el wait() del ciclo para que pueda salir
    retry_val.set()
    set_widget(buttonStop, state="disabled")


def on_close():
    stop_event.set()
    ok2run.set()
    retry_val.set()
    start_process.set()
    close_camera(cam1)
    close_camera(cam2)
    try:
        app.destroy()
    except Exception:
        pass


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

app = CTK_APP("tim inspection", (1200, 725))

tabsmainframe = app.addTab((1200, 725), (0, 0), ["Home", "Settings"], color="lightgray")
tabLogin = app.addTab((300, 600), (20, 0), ["Account"],
                      tabsmainframe["Settings"], color="gray")
tabIpAndPorts = app.addTab((300, 600), (340, 0), ["IP and Ports"],
                           tabsmainframe["Settings"], color="gray")
tabSwitches = app.addTab((300, 600), (660, 0), ["Options"],
                         tabsmainframe["Settings"], color="gray")
tabCamera1Info = app.addTab((150, 150), (1010, 115), ["Camera 1"],
                            tabsmainframe["Home"], color="gray")
tabCamera2Info = app.addTab((150, 150), (1010, 270), ["Camera 2"],
                            tabsmainframe["Home"], color="gray")
tabPlcInfo = app.addTab((150, 175), (1010, 425), ["PLC"],
                        tabsmainframe["Home"], color="gray")

# --- estado de dispositivos ---
ledSfis = app.addLed(20, (1025, 625), "red", tabsmainframe["Home"])
lblSfis = app.addLabel((0, 0), (1040, 615), "SFIS", tabsmainframe["Home"],
                       "transparent", 18, "black")

lblIpInfoCamera1 = app.addLabel((10, 10), (0, 30), "", tabCamera1Info["Camera 1"],
                                size=14, txt_color="black")
ledCamera1 = app.addLed(20, (65, 10), "red", tabCamera1Info["Camera 1"])

lblIpInfoCamera2 = app.addLabel((10, 10), (0, 30), "", tabCamera2Info["Camera 2"],
                                size=14, txt_color="black")
ledCamera2 = app.addLed(20, (65, 10), "red", tabCamera2Info["Camera 2"])

lblIpInfoPlc = app.addLabel((10, 10), (0, 30),
                            "IP:{}".format(data["devices"]["plc"]["ip"]),
                            tabPlcInfo["PLC"], size=14, txt_color="black")
lblPortInfoPlc = app.addLabel((10, 10), (0, 50),
                              "PORT:{}".format(data["devices"]["plc"]["port"]),
                              tabPlcInfo["PLC"], size=14, txt_color="black")
ledPlc = app.addLed(20, (65, 10), "red", tabPlcInfo["PLC"])

# --- consola ---
consoleLog = app.addLogBox(width=1000, height=100, bg="black", fg="lime",
                           font=("Consolas", 10), owner=tabsmainframe["Home"])
consoleLog.place(x=0, y=555)
_ui_root = consoleLog

# --- previews ---
lblCameraNumber = app.addLabel((0, 0), (0, 0), "Camera", tabsmainframe["Home"],
                               size=16, txt_color="black")
img_gui = app.addLabel((490, 500), (0, 20), "", tabsmainframe["Home"], color="black")
img_gui2 = app.addLabel((490, 500), (510, 20), "", tabsmainframe["Home"], color="black")

# --- botones ---
buttonStart = app.addButton((150, 25), (0, 525), "Start", tabsmainframe["Home"],
                            color="green", command=startButton)
buttonRestart = app.addButton((150, 25), (160, 525), "Restart", tabsmainframe["Home"],
                              color="orange", command=resetButton)
buttonStop = app.addButton((150, 25), (320, 525), "Stop", tabsmainframe["Home"],
                           color="red", command=stopButton)
buttonPhoto = app.addButton((150, 25), (480, 525), "Take a photo",
                            tabsmainframe["Home"], command=takePhoto)
buttonClearConsole = app.addButton((150, 25), (640, 525), "Clear console",
                                   tabsmainframe["Home"], color="black",
                                   command=clear_log_box)

# Start y Stop arrancan deshabilitados: no hay nada que iniciar ni detener
# hasta que el setup termine.
set_widget(buttonStart, state="disabled")
set_widget(buttonStop, state="disabled")

# --- panel de estado ---
lblPega = app.addLabel((0, 0), (1010, 0), "PEGATRON", tabsmainframe["Home"],
                       size=24, txt_color="black")
lblModel = app.addLabel((0, 0), (1010, 40), "Model:", tabsmainframe["Home"],
                        size=14, txt_color="black")
lblTotal = app.addLabel((0, 0), (1010, 70), f"Total:{total}", tabsmainframe["Home"],
                        size=14, txt_color="black")
lblISN = app.addLabel((0, 0), (1010, 100), f"ISN:{current_isn}",
                      tabsmainframe["Home"], size=14, txt_color="black")

# --- Settings: Account ---
lblLogin = app.addLabel((0, 0), (0, 0), "Login", tabLogin["Account"],
                        size=16, txt_color="black")
lblLoginSeparator = app.addLabel((0, 0), (0, 10), "_" * 34, tabLogin["Account"],
                                 size=16, txt_color="black")
entryUser = app.addEntry((280, 50), (0, 50), "User", tabLogin["Account"], size=12)
entryPass = app.addEntry((280, 50), (0, 100), "Password", tabLogin["Account"],
                         size=12, protected=1)
buttonEnterLogin = app.addButton((280, 50), (0, 160), "Save", tabLogin["Account"],
                                 size=14, command=userLogin)

# --- Settings: IP and Ports ---
lblSettingsPlc = app.addLabel((0, 0), (0, 0), "PLC", tabIpAndPorts["IP and Ports"],
                              size=16, txt_color="black")
lblIpsSeparator = app.addLabel((0, 0), (0, 10), "_" * 34,
                               tabIpAndPorts["IP and Ports"], size=16, txt_color="black")
lblIpPlc = app.addLabel((0, 0), (0, 35), "IP", tabIpAndPorts["IP and Ports"],
                        size=14, txt_color="black")
entryIpPlc = app.addEntry((280, 50), (0, 60), "IP PLC ex. 192.168.1.10",
                          tabIpAndPorts["IP and Ports"], size=12)
lblPortPlc = app.addLabel((0, 0), (0, 110), "PORT", tabIpAndPorts["IP and Ports"],
                          size=14, txt_color="black")
entryPortPlc = app.addEntry((280, 50), (0, 130), "PORT PLC ex. 502",
                            tabIpAndPorts["IP and Ports"], size=12)

lblSettingsCam = app.addLabel((0, 0), (0, 190), "Camera",
                              tabIpAndPorts["IP and Ports"], size=16, txt_color="black")
lblIps2Separator = app.addLabel((0, 0), (0, 200), "_" * 34,
                                tabIpAndPorts["IP and Ports"], size=16, txt_color="black")
lblIpCam = app.addLabel((0, 0), (0, 225), "IP camera 1",
                        tabIpAndPorts["IP and Ports"], size=14, txt_color="black")
entryIpCam = app.addEntry((280, 50), (0, 250), "IP CAMERA ex. 192.168.1.20",
                          tabIpAndPorts["IP and Ports"], size=12)
lblIpCam2 = app.addLabel((0, 0), (0, 305), "IP camera 2",
                         tabIpAndPorts["IP and Ports"], size=14, txt_color="black")
entryIpCam2 = app.addEntry((280, 50), (0, 325), "IP CAMERA 2 ex. 192.168.1.21",
                           tabIpAndPorts["IP and Ports"], size=12)

lblIpScanner = app.addLabel((0, 0), (0, 390), "IP Scanner",
                            tabIpAndPorts["IP and Ports"], size=14, txt_color="black")
entryIpScanner = app.addEntry((280, 25), (0, 410), "IP SCANNER ex. 192.168.1.30",
                              tabIpAndPorts["IP and Ports"], size=12)
lblPortScanner = app.addLabel((0, 0), (0, 440), "Port Scanner",
                              tabIpAndPorts["IP and Ports"], size=14, txt_color="black")
# El original tenía (2809, 25): un ancho de 2809 px que desbordaba la pestaña.
entryPortScanner = app.addEntry((280, 25), (0, 460), "PORT SCANNER ex. 502",
                                tabIpAndPorts["IP and Ports"], size=12)

# --- Settings: Options ---
switchActivateQuestions = app.addSwitch((20, 20), "Confirm question",
                                        tabSwitches["Options"], size=18)
switchActivateQuestionPass = app.addSwitch((20, 60), "Confirm question with pass",
                                           tabSwitches["Options"], size=18)
switchActivateSfi = app.addSwitch((20, 100), "Activate SFI",
                                  tabSwitches["Options"], size=18)
switchActivateScanner = app.addSwitch((20, 140), "Activate scanner",
                                      tabSwitches["Options"], size=18)


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------

if __name__ == "__main__":
    setInfo()
    add_log_message("Starting")

    try:
        app.protocol("WM_DELETE_WINDOW", on_close)
    except Exception:
        pass    # si CTK_APP no expone protocol(), se cierra igualmente

    threading.Thread(target=setUp, daemon=True, name="setup").start()

    app.runApp()
    on_close()
