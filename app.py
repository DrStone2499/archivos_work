#from flask import Flask, render_template, request, jsonify, send_file
from resources.PLC_Lib import *
from resources.Camera_Lib import * 
from static.config.settings import CONFIG_FILE, MEMORY_FILE, PATH_LOG
from cut_ref import *
from resources.DatalogicLib import *
from resources.sfis_module import * 
from resources.widgets import *
from configparser import RawConfigParser
from resources.hikvision_connection import *
#import webview
import threading
import json 
import os
import datetime
import time
import cv2
import base64
import sys
import shutil
import logging
import sys
import msvcrt
from ctypes import *
import numpy as np

#sys.path.append("../MvImport")
from MvCameraControl_class import *

from tkinter import messagebox
#app = Flask(__name__)
var_setUp = [0,0,0,0]
myPlc = []
dataPlc = ''
cam1 = ''
cam2 = ''
system = 0
img_aux = ''
mode = 'production'
scanner = ''
config = RawConfigParser(allow_no_value=True)
fp = open(r"resources/config.ini", "r", encoding="utf-8-sig")
config.read_file(fp)
year = f"{datetime.datetime.now().year}"
month = f"{datetime.datetime.now().month:02}"
day = f"{datetime.datetime.now().day:02}"
hour = f"{datetime.datetime.now().hour:02}"
minute = f"{datetime.datetime.now().minute:02}"
total = ''
isn = ''
started = 0
start_process = threading.Event()
retry_val = threading.Event()
ok2run = threading.Event()
log = os.path.join(os.getcwd(), "log")

with open(CONFIG_FILE, 'r') as f: data = json.load(f)
if data:print('json loaded')

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)
def load_memorys():
    with open(MEMORY_FILE, 'r') as f:
        return json.load(f)
def load_dataTime():
    global year,month,day,hour,minute
    year = f"{datetime.datetime.now().year}"
    month = f"{datetime.datetime.now().month:02}"
    day = f"{datetime.datetime.now().day:02}"
    hour = f"{datetime.datetime.now().hour:02}"
    minute = f"{datetime.datetime.now().minute:02}"

def save_config(data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def writeLog(img, isn, n , imgaux, result):
    isn_clean = isn.replace(":","")
    names = [f"{isn_clean}_Top_1.jpg", f"{isn_clean}_Top_2.jpg"]
    pathToWrite = os.path.join(PATH_LOG, isn_clean)

    if not os.path.join(PATH_LOG, isn_clean):
        os.makedirs(pathToWrite)
    cv2.imwrite(os.path.join(pathToWrite, names[n]), img)
    cv2.imwrite(os.path.join(pathToWrite, f"Result_{n}.jpg"), imgaux)  

def writeLogSFIS(path, txt, ISN):
    # name = [fr"\{ISN}_Top_1.jpg",fr"\{ISN}_Top_2.jpg"]
    # print(ISN)
    ISN = ISN.replace(":", "")
    pathTowrite = os.path.join(path, ISN)

    if not os.path.exists(pathTowrite):
        os.makedirs(pathTowrite)
    with open(
        os.path.join(pathTowrite, "result.txt"), "w", encoding="utf-8"
    ) as archivo:
        archivo.write(txt)
    # cv2.imwrite(os.path.join(path,ISN,f"Result_{n}.jpg"),img_aux)       


# -- pages --------------------------------------------------------------------------------


# -- API ----------------------------------------------------------------------------------
def setInfo():
    if data:
        entryUser.insert(0, f"{str(data['user'])}")
        entryIpPlc.insert(0, f"{str(data['devices']['plc']['ip'])}")
        entryPortPlc.insert(0, f"{str(data['devices']['plc']['port'])}")
        entryIpCam.insert(0, f"{str(data['devices']['cam1']['ip'])}")
        entryIpCam2.insert(0, f"{str(data['devices']['cam2']['ip'])}")
        entryIpScanner.insert(0, f"{str(data['devices']['scanner']['ip'])}")
        entryPortScanner.insert(0, f"{str(data['devices']['scanner']['port'])}")
        if data["question"] == 1:
            switchActivateQuestions.select()
        else:
            switchActivateQuestions.deselect()
        if data["question_pass"] == 1:
            switchActivateQuestions.select()
        else:
            switchActivateQuestions.deselect()
        if data["sfis"] == 1:
            switchActivateSfi.select()
        else:
            switchActivateSfi.deselect()
        if data["scanner"] == 1:
            switchActivateScanner.select()
        else:
            switchActivateScanner.deselect()

def userLogin():
    user = entryUser.get()
    password = entryPass.get()

    try:
        if data["user"] != user or data["password"] != password:
            messagebox.showerror("Error", "User or password wrong.")
        else:
            if (
                entryIpPlc.get()
                and entryPortPlc.get()
                and entryIpCam.get()
                and entryIpCam2.get()
            ):

                new_data = {
                    "user": data["user"],
                    "password": data["password"],
                    "question": switchActivateQuestions.get(),
                    "question_pass": switchActivateQuestionPass.get(),
                    "sfis": switchActivateSfi.get(),
                    "scanner": switchActivateScanner.get(),

                    "devices":{
                        "cam1":{
                            "ip": entryIpCam.get()
                        },
                        "cam2":{
                            "ip": entryIpCam2.get()
                        },
                        "plc": {
                            "ip":entryIpPlc.get(),
                            "port": entryPortPlc.get()
                        },
                        "scanner":{
                            "ip": entryIpScanner.get(),
                            "port": int(entryPortScanner.get())
                        }

                    }
                }
                try:
                    with open(CONFIG_FILE, "w") as file:
                        json.dump(new_data, file, indent=4)
                        lblIpInfoCamera1.configure(text=f"IP:{new_data["devices"]["cam1"]["ip"]}")
                        lblIpInfoCamera2.configure(text=f"IP:{new_data["devices"]["cam2"]["ip"]}")
                        lblIpInfoPlc.configure(text=f"IP:{new_data["devices"]["plc"]["ip"]}")
                        lblPortInfoPlc.configure(text=f"PORT:{new_data["devices"]["plc"]["port"]}")
                        print(f"Data save: {new_data}")
                except IOError as e:
                    print(f"Error: {str(e)}")
            else:
                messagebox.showinfo("Error", "Missing some data.")
    except Exception as e:
        add_log_message(f"--- {hour}:{minute} --- {str(e)}")

def verificar_disco(ruta="/", umbral_alerta=99):
    # Obtener estadísticas de uso
    total, usado, libre = shutil.disk_usage(ruta)

    # Calcular el porcentaje de uso
    porcentaje_usado = (usado / total) * 100

    print(f"Uso actual: {porcentaje_usado:.2f}%")

    if porcentaje_usado >= umbral_alerta:
        print(f"\n¡ALERTA! El disco está al {porcentaje_usado:.2f}% de su capacidad.")
        # Arrojar la pregunta al usuario
        x = app.addPopUp(
            "There is not enough space on the disk",
            "CLEAN THE LOG AND CLICK RETRY PLEASE",
            ["No", "Retry"],
        )

        if x:
            print("Operación cancelada por falta de espacio.")
            return verificar_disco()
        else:
            return verificar_disco()

    return True

def UpdateImage(img, camera):
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (490, 500))
    img_pil = Image.fromarray(img)
    img_ctk = ctk.CTkImage(img_pil, size=(490, 500))
    if camera == 0:
        lblCameraNumber.configure(text="Camera 1")
        img_gui.configure(image=img_ctk)
    else:
        lblCameraNumber.configure(text="Camera 2")
        img_gui2.configure(image=img_ctk)


def takePhoto():
    global cam1, cam2
    if started == 0:
        x = app.addPopUp(
            "TAKE A PHOTO",
            "Which camera wanted to take a photo?",
            ["Camera 1", "Camera 2"],
        )
        if x:
            try:
                add_log_message(f"--- {hour}:{minute} --- Camera 2")
                cam2.takePicture()
                print(cam2.takePicture())
                img = cam2.getImg()
                UpdateImage(img, 1)
                # cv2.imshow("test",img)
                # cv2.waitKey(0)
            except Exception as e:
                add_log_message(str(f"--- {hour}:{minute} --- error:{e} ---"))
        else:
            try:
                add_log_message("--- Camera 1")
                cam1.takePicture()
                print(cam1.takePicture())
                img = cam1.getImg()
                UpdateImage(img, 0)
                # cv2.imshow("test",img)
                # cv2.waitKey(0)
            except Exception as e:
                add_log_message(str(f"--- {hour}:{minute} --- error:{e}"))

def work_photo(cam=0, pData=0, nDataSize=0):
    #global g_bExit
    stOutFrame = MV_FRAME_OUT()  
    memset(byref(stOutFrame), 0, sizeof(stOutFrame))
    
    #cv2.namedWindow("Camara MVS - En Vivo", cv2.WINDOW_NORMAL)
    
    #while True:
    ret = cam.MV_CC_GetImageBuffer(stOutFrame, 1000)
    if None != stOutFrame.pBufAddr and 0 == ret:
        # 1. Copiar los bytes crudos desde la memoria de la cámara
        pData = (c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
        memmove(pData, stOutFrame.pBufAddr, stOutFrame.stFrameInfo.nFrameLen)
        
        # 2. Convertir buffer a arreglo lineal uint8
        frame_data = np.frombuffer(pData, dtype=np.uint8)
        
        # CORRECCIÓN AQUÍ: Agregamos el parámetro ', 2' al final de la tupla 
        # para estructurar la matriz con los 2 canales que exige cv2.cvtColor
        yuv_frame = frame_data.reshape((stOutFrame.stFrameInfo.nHeight, stOutFrame.stFrameInfo.nWidth, 2))
        
        # 3. Decodificar el formato YUV (YUYV) empaquetado directamente a BGR
        frame_final = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_YUYV)

        # 4. Liberar el buffer de la cámara de manera segura
        cam.MV_CC_FreeImageBuffer(stOutFrame)
        
        # 5. Redimensionar y mostrar la imagen en color real
        # frame_resized = cv2.resize(frame_final, None, fx=0.20, fy=0.20)
        # cv2.imshow("Camara MVS - En Vivo", frame_resized)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()

        return frame_final
        # Permitir cerrar la transmisión presionando la tecla 'q'

    else:
        print("no data[0x%x]" % ret)
        return None
        #if g_bExit == True:
            #break

def open_camera(n):
    deviceList = MV_CC_DEVICE_INFO_LIST()
    tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE

    ret = MvCamera.MV_CC_EnumDevices(tlayerType, deviceList)
    if ret != 0:
        print("enum devices fail! ret[%x]" % ret)
        return None
        #sys.exit()
    if deviceList.nDeviceNum == 0:
        print("find no devices!")
        return None
        #sys.exit()

    print("Find %d devices!" % deviceList.nDeviceNum)

    for i in range(0, deviceList.nDeviceNum):
        mvcc_dev_info = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
        if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE:
            print ("\ngige device: [%d]" % i)
            strModeName = ""
            for per in mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName:
                strModeName = strModeName + chr(per)
            print ("device model name: %s" % strModeName)

            nip1 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0xff000000) >> 24)
            nip2 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x00ff0000) >> 16)
            nip3 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x0000ff00) >> 8)
            nip4 = (mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x000000ff)
            print ("current ip: %d.%d.%d.%d\n" % (nip1, nip2, nip3, nip4))
            ip = f"{nip1}.{nip2}.{nip3}.{nip4}"
        elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
            print ("\nu3v device: [%d]" % i)
            strModeName = ""
            for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName:
                if per == 0:
                    break
                strModeName = strModeName + chr(per)
            print ("device model name: %s" % strModeName)

            strSerialNumber = ""
            for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber:
                if per == 0:
                    break
                strSerialNumber = strSerialNumber + chr(per)
            print ("user serial number: %s" % strSerialNumber)
            
            
        nConnectionNum = n
        cam = MvCamera()
        stDeviceList = cast(deviceList.pDeviceInfo[int(nConnectionNum)], POINTER(MV_CC_DEVICE_INFO)).contents

        ret = cam.MV_CC_CreateHandle(stDeviceList)
        if ret != 0:
            print ("create handle fail! ret[0x%x]" % ret)
            return None, None
            #sys.exit()

        ret = cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            print ("open device fail! ret[0x%x]" % ret)
            return None, None
            #sys.exit()

        if stDeviceList.nTLayerType == MV_GIGE_DEVICE:
            nPacketSize = cam.MV_CC_GetOptimalPacketSize()
            if int(nPacketSize) > 0:
                ret = cam.MV_CC_SetIntValue("GevSCPSPacketSize",nPacketSize)
                if ret != 0:
                    print ("Warning: Set Packet Size fail! ret[0x%x]" % ret)
                    return None, None
            else:
                print ("Warning: Get Packet Size fail! ret[0x%x]" % nPacketSize)
                return None, None

        stBool = c_bool(False)
        ret =cam.MV_CC_GetBoolValue("AcquisitionFrameRateEnable", stBool)
        if ret != 0:
            print ("get AcquisitionFrameRateEnable fail! ret[0x%x]" % ret)
            return None, None

        # ch:设置触发模式为off | en:Set trigger mode as off
        ret = cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
        if ret != 0:
            print ("set trigger mode fail! ret[0x%x]" % ret)
            return None, None
            #sys.exit()

        ret = cam.MV_CC_StartGrabbing()
        if ret != 0:
            print ("start grabbing fail! ret[0x%x]" % ret)
            return None, None
            #sys.exit()
        return cam, ip


    
#@app.route('/api/setUp')
def setUp():
    global cam1,cam2, myPlc, var_setUp, system, started, dataPlc
    datos = load_config()
    # dataCam = data["devices"]["cam1"]
    # dataCam2 = data["devices"]["cam2"]
    dataPlc = datos["devices"]["plc"]
    # dataScanner = data["scanner"]
    dataSfis = datos["sfis"]

    load_dataTime()
    #log = os.path.join(os.getcwd(), "log")
    #print(dataCam, dataPlc)
    while not ok2run.is_set():
        #if not 1 in var_setUp:
        if var_setUp[0] == 0:
            if mode == 'develop':
                var_setUp[0] = 1
                add_log_message(f"--- {hour}:{minute} --- PLC connected develop mode")
                ledPlc.configure(fg_color="green")
            else:
                #print(data['devices']["plc"]['ip'], int(data['devices']["plc"]['port']))
                myPlc = SLMP_PLC(dataPlc["ip"], int(dataPlc["port"]))
                #print('this is',myPlc.client)
                if myPlc.client != None:
                    #print("entro al if")
                    add_log_message(f"--- {hour}:{minute} --- PLC connected")
                    ledPlc.configure(fg_color="green")
                    var_setUp[0] = 1          
                else:
                    #print("entro al else")
                    if var_setUp[0] != 1:
                        var_setUp[0] = 0
                        add_log_message(f"--- {hour}:{minute} --- PLC FAIL connection")
                        ledPlc.configure(fg_color="red")

        if var_setUp[1] == 0:
            if mode == 'develop':
                add_log_message(f"--- {hour}:{minute} --- SFIS connected develop mode")
                ledSfis.configure(fg_color="green")
                var_setUp[1] = 1
            else:
                if dataSfis == 1:
                    if var_setUp[1] == 0:
                        print(logout(config.get('SFIS','op_id'), device=config.get('SFIS', 'device')))
                        sfis_message = login(config.get('SFIS','op_id'), device=config.get('SFIS', 'device'))
                        print(sfis_message)
                        if int(sfis_message[0])  == 1:
                            var_setUp[1] = 1
                            add_log_message(f"--- {hour}:{minute} --- SFIS connected")
                            ledSfis.configure(fg_color="green")
                        
                else:
                    if var_setUp[1] != 1:
                        ledSfis.configure(fg_color="red")
                        add_log_message(f"--- {hour}:{minute} --- SFIS not connected")
                        var_setUp[1] = 1

        if var_setUp[2] == 0:
            if mode == 'develop':
                var_setUp[2] = 1
                add_log_message(f"--- {hour}:{minute} --- Camera 1 connected develop mode")
                ledCamera1.configure(fg_color="green")
            else:
                cam1, ip = open_camera(0)
                #cam1 = BASLER(dataCam["ip"])
                if cam1 != None:
                    var_setUp[2] = 1
                    add_log_message(f"--- {hour}:{minute} --- Camera 1 connected")
                    lblIpInfoCamera1.configure(text=f"IP:{ip}")
                    ledCamera1.configure(fg_color="green")
                else:
                    if var_setUp[2] != 1:
                        var_setUp[2] = 0
                        ledCamera1.configure(fg_color="red")
                        add_log_message(f"--- {hour}:{minute} --- Camera 1 not connected")

                
        if var_setUp[3] == 0:
            if mode == 'develop':
                var_setUp[3] = 1
                add_log_message(f"--- {hour}:{minute} --- Camera 2 connected develop mode")
                ledCamera2.configure(fg_color="green")
            else:
                cam2, ip = open_camera(1)
                #cam1 = BASLER(dataCam["ip"])
                if cam2 != None:
                    var_setUp[3] = 1
                    add_log_message(f"--- {hour}:{minute} --- Camera 2 connected")
                    lblIpInfoCamera2.configure(text=f"IP:{ip}")
                    ledCamera2.configure(fg_color="green")
                else:
                    if var_setUp[3] != 1:
                        var_setUp[3] = 0
                        ledCamera2.configure(fg_color="red")
                        add_log_message(f"--- {hour}:{minute} --- Camera 2 not connected")
        else:
            var_setUp[3] = 1
            add_log_message(f"--- {hour}:{minute} --- Camera 2 connected bypass")
            ledCamera2.configure(fg_color="green")
        print(var_setUp)
        if 0 not in var_setUp:
            break
        add_log_message(f"--- {hour}:{minute} ---  Please press reset to try again")
        retry_val.wait()
        retry_val.clear()

    print(var_setUp)
    add_log_message(f"--- {hour}:{minute} ---  Program ready to start")
    ok2run.set()
    system = 1
    start_process.wait()
    started = 1
    run_main_loop()
        # m = threading.Thread(target=run_main_loop)
        # m.daemon = True
        # m.start()
            

        
def run_main_loop():
    global system, img_aux,year,month,day,hour,minute,cam1,cam2, myPlc, var_setUp, dataPlc
    
    myPlc = SLMP_PLC(dataPlc["ip"], int(dataPlc["port"]))
    #print("holaa")
    while True:
        year = f"{datetime.datetime.now().year}"
        month = f"{datetime.datetime.now().month:02}"
        day = f"{datetime.datetime.now().day:02}"
        hour = f"{datetime.datetime.now().hour:02}"
        minute = f"{datetime.datetime.now().minute:02}"
        dataMemory = load_memorys()
        data = load_config()
        dataScanner = data["devices"]["scanner"]
        final_result = ''
        #load_dataTime()
        log_path = ""
        log_path = os.path.join(log, year, month, day)
        ok2run.wait()
        time.sleep(0.2)
        try:
            print('memoria',dataMemory["step"])
            print("myplc",myPlc)
            print('my read plc d memori',myPlc.read_Dmemory(dataMemory["step"]))
            step = myPlc.read_Dmemory(dataMemory["step"])
            print('step',step[0])
            if step[0] != 110:
                continue

            if data["scanner"] == 1:
                isn = readQR(data["ip_scanner"], data["port_scanner"])
                # isn_sfis = isn
                lblISN.configure(text=f"ISN:{str(isn)}")
            else:
                isn = hour + minute + "_" + month + "_" + day + "_" + year
                lblISN.configure(text=f"ISN:{str(isn)}")

            if data["sfis"] == 1 and data["scanner"] == 1:
                try:
                    logout(config.get("SFIS", "op_id"), device=config.get("SFIS", "device"))
                    login(config.get("SFIS", "op_id"), device=config.get("SFIS", "device"))
                    isn = isn.replace("_", ":")
                    sfis_message = check_route(isn, device=config.get("SFIS", "device"))
                except Exception as e:
                    add_log_message(f"--- CHECK ROUTE --- {str(e)} ---")
                    return run_main_loop()
            else:
                sfis_message = [1]
            if int(sfis_message[0]) == 1:
                if mode != 'develop':
                    isn = readQR(dataScanner['ip'],dataScanner['port'])
                    myPlc.active_Mmemory(dataMemory["light_source1"])
                    myPlc.active_Mmemory(dataMemory["light_source2"])
                    time.sleep(0.1)
                    # cam1.takePhoto()
                    # img = cam1.getImage()
                    img = work_photo(cam1, None, None)
                    time.sleep(0.1)
                else:
                    path_img = input("path image 1 :")
                    img = cv2.imread(path_img)
                if img == None:
                    print("no photo first camera")
                    return run_main_loop()
                result_count,result_info, img_aux = timFunction(img,0,step[0])
                UpdateImage(img_aux,0)
                for name,(values) in result_info.items():
                    print(name, values['status'])
                step2 = [120]
                if mode != 'develop':
                    # cam2.takePicture()
                    # img2 = cam2.getImg()
                    img2  = work_photo(cam1, None, None)
                    time.sleep(0.1)
                else:
                    path_img = input("path image 2 :")
                    img2 = cv2.imread(path_img)
                if img2 == None:
                    print("no photo")
                    return run_main_loop()
                result_count2,result_info2, img_aux2 = timFunction(img2,1,step2[0])
                UpdateImage(img_aux2,1)
                for name,(values) in result_info2.items():
                    print(name, values['status'])
                myPlc.desactive_Mmemory(dataMemory["light_source1"])
                myPlc.desactive_Mmemory(dataMemory["light_source2"])
                if 0 in result_count:
                    x, y = app.addPopUp('Test fail','test fail, retry?',['NG','OK','RETRY'])
                    if y == True:
                        print("se mando retry")
                        return run_main_loop()
                    if x == True:
                        print("se mando ok")
                        add_log_message(
                            f"--- {hour}:{minute} --- OK Result first test"
                        )
                        final_result.append(1)
                        #total += 1
                        #lblTotal.configure(text=f"Total:{total}")
                        continue
                    else:
                        print('se mando ng')
                        if verificar_disco():
                            print("Espacio suficiente. Iniciando proceso...")
                            real_log = os.path.join(log_path, "NG")
                            writeLog(real_log, img, isn, 0, img_aux)
                            time.sleep(1)
                            writeLog(real_log, img2, isn, 1, img_aux2)
                            time.sleep(1)
                            final_result.append(0)
                            data2sfis = (
                                f"TEST,TSTATUS,TVALUE,UCL,LCL\n"
                                + f"AOItest,{0 if 0 in final_result else 1},{0 if 0 in final_result else 1},0,2"
                            )
                            writeLogSFIS(real_log, data2sfis, isn)
                            final_result.clear()
                            result_count.clear()
                            result_info.clear()
                            #login(config.get("SFIS", "op_id"), device=config.get("SFIS", "device"))
                            send_result(isn, config.get("SFIS", "device"), config.get("SFIS", "sfis_error") if final_result == 0 else "", config.get("SFIS", "tsp"), data2sfis)
                            logout(config.get("SFIS", "op_id"), device=config.get("SFIS", "device"))
                            myPlc.active_Mmemory(dataMemory["NG"])
                            add_log_message(f"--- {hour}:{minute} --- NG Result first test")
                            total += 1
                            lblTotal.configure(text=f"Total:{total}")
                            break
                else:
                    continue
                if 0 in result_count2:
                    x, y = app.addPopUp('Test 2 fail','test 2 fail, retry?',['NG','OK','RETRY'])
                    if y == True:
                        print("se mando retry")
                        return run_main_loop()
                    if x == True:
                        print("se mando ok")
                        final_result.append(1)
                        add_log_message(f"--- {hour}:{minute} --- OK Result second test")
                        continue
                    else:
                        print('se mando ng')
                        if verificar_disco():
                            print("Espacio suficiente. Iniciando proceso...")
                            real_log = os.path.join(log_path, "NG")
                            writeLog(real_log, img, isn, 0, img_aux)
                            time.sleep(1)
                            writeLog(real_log, img2, isn, 1, img_aux2)
                            time.sleep(1)
                            final_result.append(0)
                            data2sfis = (
                                f"TEST,TSTATUS,TVALUE,UCL,LCL\n"
                                + f"AOItest,{0 if 0 in final_result else 1},{0 if 0 in final_result else 1},0,2"
                            )
                            #riteLogSFIS(real_log, data2sfis, isn)
                            send_result(isn, config.get("SFIS", "device"), config.get("SFIS", "sfis_error") if final_result == 0 else "", config.get("SFIS", "tsp"), data2sfis)
                            logout(config.get("SFIS", "op_id"), device=config.get("SFIS", "device"))
                            final_result.clear()
                            result_count.clear()
                            result_info.clear()
                            myPlc.active_Mmemory(dataMemory["NG"])
                            add_log_message(f"--- {hour}:{minute} --- NG result second test")
                            total += 1
                            lblTotal.configure(text=f"Total:{total}")
                            break                  
                else:
                    continue
                if verificar_disco():
                    print("Espacio suficiente. Iniciando proceso...")
                    real_log = os.path.join(log_path, "OK")
                    writeLog(real_log, img, isn, 0, img_aux)
                    time.sleep(1)
                    writeLog(real_log, img2, isn, 1, img_aux2)
                    time.sleep(1)
                    data2sfis = (
                        f"TEST,TSTATUS,TVALUE,UCL,LCL\n"
                        + f"AOItest,{0 if 0 in final_result else 1},{0 if 0 in final_result else 1},0,2"
                    )
                    writeLogSFIS(real_log, data2sfis, isn)
                    final_result.clear()
                    result_count.clear()
                    result_info.clear()
                    if data['sfis'] == 1:
                        #login(config.get("SFIS", "op_id"), device=config.get("SFIS", "device"))
                        send_result(isn, config.get("SFIS", "device"), config.get("SFIS", "sfis_error") if final_result == 0 else "", config.get("SFIS", "tsp"), data2sfis)
                        logout(config.get("SFIS", "op_id"), device=config.get("SFIS", "device"))
                    myPlc.active_Mmemory(dataMemory["OK"])
                    add_log_message(f"--- {hour}:{minute} --- OK Result to the memory ")
                    total += 1
                    lblTotal.configure(text=f"Total:{total}")
                    break
            else:
                #myPlc.active_Mmemory(dataM["triggerAlarm"])
                add_log_message(f"--- {hour}:{minute} --- Wrong route")
                add_log_message(f"--- {hour}:{minute} --- {str(sfis_message)}")
                x = app.addPopUp(
                    "Test",
                    "Please press emergency stop and remove PCBA",
                    ["Cancel", "Continue"],
                )
                if x == True:
                    continue
                else:
                    return run_main_loop()
        except Exception as e:
            print(e)

                



def add_log_message(message):
    # Asegúrate de que 'consoleLog' sea una variable global o esté accesible en este scope
    global consoleLog

    # 1. Habilitar temporalmente la edición
    consoleLog.configure(state="normal")

    # 2. Insertar el mensaje al final del texto existente (tk.END)
    consoleLog.insert(tk.END, message + "\n")

    # 3. Desplazar automáticamente hacia la última línea para que sea visible
    consoleLog.see(tk.END)

    # 4. Deshabilitar de nuevo para proteger el log
    consoleLog.configure(state="disabled")

def clear_log_box():
    global consoleLog

    # 1. Habilitar temporalmente la edición
    consoleLog.configure(state="normal")

    # 2. Borrar todo el texto desde el principio (1.0) hasta el final (tk.END)
    consoleLog.delete("1.0", tk.END)

    # 3. Deshabilitar de nuevo el log
    consoleLog.configure(state="disabled")

def startButton():
    global started
    if ok2run.is_set() and started == 0:
        add_log_message(f"--- {hour}:{minute} --- Start pressed")
        # cambiar color boton
        start_process.set()
    if not ok2run.is_set() and started == 1:
        add_log_message(f"--- {hour}:{minute} --- Start pressed")
        # cambiar color boton
        ok2run.set()



def resetButton():
    global started
    # lbls = [ledCamera1,ledCamera2, ledPlc, ledSfis]
    if started == 0 and not ok2run.is_set():
        add_log_message(f"--- {hour}:{minute} --- Restarting")
        retry_val.set()
        started = 0


def stopButton():
    print('stop')
# ---------------------GUI----------------------#

app = CTK_APP("tim inspection", (1200, 725))

tabsmainframe = app.addTab(
    (1200, 725), (0, 0), ["Home", "Settings"], color="lightgray"
)
tabLogin = app.addTab(
    (300, 600), (20, 0), ["Account"], tabsmainframe["Settings"], color="gray"
)
tabIpAndPorts = app.addTab(
    (300, 600), (340, 0), ["IP and Ports"], tabsmainframe["Settings"], color="gray"
)
tabSwitches = app.addTab(
    (300, 600), (660, 0), ["Options"], tabsmainframe["Settings"], color="gray"
)
tabCamera1Info = app.addTab(
    (150, 150), (1010, 115), ["Camera 1"], tabsmainframe["Home"], color="gray"
)
tabCamera2Info = app.addTab(
    (150, 150), (1010, 270), ["Camera 2"], tabsmainframe["Home"], color="gray"
)
tabPlcInfo = app.addTab(
    (150, 175), (1010, 425), ["PLC"], tabsmainframe["Home"], color="gray"
)
ledSfis = app.addLed(20, (1025, 625), "red", tabsmainframe["Home"])
lblSfis = app.addLabel(
    (0, 0), (1040, 615), "SFIS", tabsmainframe["Home"], "transparent", 18, "black"
)

consoleLog = app.addLogBox(
    width=1000,
    height=100,
    bg="black",
    fg="lime",
    font=("Consolas", 10),
    owner=tabsmainframe["Home"],
)
consoleLog.pack(padx=10, pady=10, anchor="sw")
consoleLog.place(x=0, y=555)

lblIpInfoCamera1 = app.addLabel(
    (10, 10),
    (0, 30),
    "",
    tabCamera1Info["Camera 1"],
    size=14,
    txt_color="black",
)
ledCamera1 = app.addLed(20, (65, 10), "red", tabCamera1Info["Camera 1"])
lblIpInfoCamera2 = app.addLabel(
    (10, 10),
    (0, 30),
    "",
    tabCamera2Info["Camera 2"],
    size=14,
    txt_color="black",
)
ledCamera2 = app.addLed(20, (65, 10), "red", tabCamera2Info["Camera 2"])

lblIpInfoPlc = app.addLabel(
    (10, 10),
    (0, 30),
    f"IP:{data['devices']['plc']['ip']}",
    tabPlcInfo["PLC"],
    size=14,
    txt_color="black",
)
lblPortInfoPlc = app.addLabel(
    (10, 10),
    (0, 50),
    f"PORT:{data['devices']['plc']['port']}",
    tabPlcInfo["PLC"],
    size=14,
    txt_color="black",
)
ledPlc = app.addLed(20, (65, 10), "red", tabPlcInfo["PLC"])

lblCameraNumber = app.addLabel(
    (0, 0), (0, 0), "Camera", tabsmainframe["Home"], size=16, txt_color="black"
)
img_gui = app.addLabel((490, 500), (0, 20), "", tabsmainframe["Home"], color="black")
img_gui2 = app.addLabel((490, 500), (510, 20), "", tabsmainframe["Home"], color="black")


# -------------------HOME section-----------------------------#
# buttons
buttonStart = app.addButton(
    (150, 25),
    (0, 525),
    "Start",
    tabsmainframe["Home"],
    color="green",
    command=startButton,
)
buttonRestart = app.addButton(
    (150, 25),
    (160, 525),
    "Restart",
    tabsmainframe["Home"],
    color="orange",
    command=resetButton,
)
buttonStop = app.addButton(
    (150, 25),
    (320, 525),
    "Stop",
    tabsmainframe["Home"],
    color="red",
    command=stopButton,
)
buttonPhoto = app.addButton(
    (150, 25), (480, 525), "Take a photo", tabsmainframe["Home"], command=takePhoto
)
buttonClearConsole = app.addButton(
    (150, 25),
    (640, 525),
    "Clear console",
    tabsmainframe["Home"],
    color="black",
    command=clear_log_box,
)


# status section
# lbl
lblPega = app.addLabel(
    (0, 0), (1010, 0), "PEGATRON", tabsmainframe["Home"], size=24, txt_color="black"
)
lblModel = app.addLabel(
    (0, 0), (1010, 40), "Model:", tabsmainframe["Home"], size=14, txt_color="black"
)
lblTotal = app.addLabel(
    (0, 0),
    (1010, 70),
    f"Total:{total}",
    tabsmainframe["Home"],
    size=14,
    txt_color="black",
)
lblISN = app.addLabel(
    (0, 0), (1010, 100), f"ISN:{isn}", tabsmainframe["Home"], size=14, txt_color="black"
)

# -----------------------------SETTINGS section--------------------#
# test = app.addFrame((800,200),(0,300),tabsmainframe["Login"])
# labels
lblLoginSeparator = app.addLabel(
    (0, 0),
    (0, 10),
    "__________________________________",
    tabLogin["Account"],
    size=16,
    txt_color="black",
)
lblLogin = app.addLabel(
    (0, 0), (0, 0), "Login", tabLogin["Account"], size=16, txt_color="black"
)

lblIpsSeparator = app.addLabel(
    (0, 0),
    (0, 10),
    "__________________________________",
    tabIpAndPorts["IP and Ports"],
    size=16,
    txt_color="black",
)
lblSettingsPlc = app.addLabel(
    (0, 0), (0, 0), "PLC", tabIpAndPorts["IP and Ports"], size=16, txt_color="black"
)

lblIpPlc = app.addLabel(
    (0, 0), (0, 35), "IP", tabIpAndPorts["IP and Ports"], size=14, txt_color="black"
)
lblPortPlc = app.addLabel(
    (0, 0), (0, 110), "PORT", tabIpAndPorts["IP and Ports"], size=14, txt_color="black"
)
lblIps2Separator = app.addLabel(
    (0, 0),
    (0, 200),
    "__________________________________",
    tabIpAndPorts["IP and Ports"],
    size=16,
    txt_color="black",
)
lblSettingsCam = app.addLabel(
    (0, 0),
    (0, 190),
    "Camera",
    tabIpAndPorts["IP and Ports"],
    size=16,
    txt_color="black",
)
lblIpScanner = app.addLabel(
    (0, 0),
    (0, 390),
    "IP Scanner",
    tabIpAndPorts["IP and Ports"],
    size=14,
    txt_color="black",
)
lblPortScanner = app.addLabel(
    (0, 0),
    (0, 440),
    "Port Scanner",
    tabIpAndPorts["IP and Ports"],
    size=14,
    txt_color="black",
)
lblIpCam = app.addLabel(
    (0, 0),
    (0, 225),
    "IP camera 1",
    tabIpAndPorts["IP and Ports"],
    size=14,
    txt_color="black",
)
lblIpCam2 = app.addLabel(
    (0, 0),
    (0, 305),
    "IP camera 2",
    tabIpAndPorts["IP and Ports"],
    size=14,
    txt_color="black",
)
# entry
entryUser = app.addEntry((280, 50), (0, 50), "User", tabLogin["Account"], size=12)
entryPass = app.addEntry(
    (280, 50), (0, 100), "Password", tabLogin["Account"], size=12, protected=1
)
entryIpPlc = app.addEntry(
    (280, 50),
    (0, 60),
    "IP PLC ex. 192.162.1.10",
    tabIpAndPorts["IP and Ports"],
    size=12,
)
entryPortPlc = app.addEntry(
    (280, 50), (0, 130), "PORT PLC ex.502", tabIpAndPorts["IP and Ports"], size=12
)
entryIpCam = app.addEntry(
    (280, 50),
    (0, 250),
    "IP CAMERA ex.192.162.1.20",
    tabIpAndPorts["IP and Ports"],
    size=12,
)
entryIpCam2 = app.addEntry(
    (280, 50),
    (0, 325),
    "IP CAMERA 2 ex.192.162.1.20",
    tabIpAndPorts["IP and Ports"],
    size=12,
)
entryIpScanner = app.addEntry(
    (289, 25),
    (0, 410),
    "IP SCANNER  ex.192.168.1.20",
    tabIpAndPorts["IP and Ports"],
    size=12,
)
entryPortScanner = app.addEntry(
    (2809, 25), (0, 460), "port SCANNER ex.502", tabIpAndPorts["IP and Ports"], size=12
)
# buttons
buttonEnterLogin = app.addButton(
    (280, 50), (0, 160), "Save", tabLogin["Account"], size=14, command=userLogin
)
# Switch
switchActivateQuestions = app.addSwitch(
    (20, 20), "Confirm question", tabSwitches["Options"], size=18
)
switchActivateQuestionPass = app.addSwitch(
    (20, 60), "Confirm question with pass", tabSwitches["Options"], size=18
)
switchActivateSfi = app.addSwitch(
    (20, 100), "Activate SFI", tabSwitches["Options"], size=18
)
switchActivateScanner = app.addSwitch(
    (20, 140), "Activate scanner", tabSwitches["Options"], size=18
)
# ledPlc.configure(fg_color = "green")



add_log_message(f"--- {hour}:{minute} ---  starting")
#setInfo()

threading.Thread(target=setUp, daemon=True).start()

setInfo()

app.runApp()