import cv2
import numpy as np
import json
from static.config.settings import ROI_FILE, REF_PATH1, REF_PATH2

def hsvInspection(img,coords_array,offset_x, offset_y,step):
    with open(ROI_FILE,"r") as f: data = json.load(f)
    #img = cv2.imread(image)
    img_aux = img.copy()
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if step == 110:
        # ---- 1. Pegamento beige ----
        lower_beige = np.array(data['lower_beige'])
        upper_beige = np.array(data['upper_beige'])
        mask_beige = cv2.inRange(hsv, lower_beige, upper_beige)
        # cv2.imshow('mask beige', mask_beige)
        # cv2.waitKey(0)

        # ---- 2. Pegamento gris (baja saturación, pero con brillo) ----
        lower_gray = np.array(data['lower_gray'])
        upper_gray = np.array(data['upper_gray'])
        mask_gray = cv2.inRange(hsv, lower_gray, upper_gray)
        # cv2.imshow('mask gray', mask_gray)
        # cv2.waitKey(0)
        # ---- 3. Textura (muy importante) ----
        edges = cv2.Canny(gray, 50, 150)
        # cv2.imshow('edges',edges)
        # cv2.waitKey(0)
        # ---- combinar máscaras ----
        mask_combined = cv2.bitwise_or(mask_beige, mask_gray)
        # cv2.imshow('mask combined', mask_combined)
        # cv2.waitKey(0)
        # limpiar ruido
        kernel = np.ones((5,5), np.uint8)
        mask_combined = cv2.morphologyEx(mask_combined, cv2.MORPH_CLOSE, kernel)
        # cv2.imshow('mask combined', mask_combined)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()
    else:
        # ---- 1. Pegamento beige ----
        lower_pink = np.array(data['lower_pink'])
        upper_pink = np.array(data['upper_pink'])
        mask_pink = cv2.inRange(hsv, lower_pink, upper_pink)

        # ---- 2. Pegamento gris (baja saturación, pero con brillo) ----
        lower_dark = np.array(data['lower_dark'])
        upper_dark = np.array(data['upper_dark'])
        mask_dark = cv2.inRange(hsv, lower_dark, upper_dark)

        # ---- 3. Textura (muy importante) ----
        edges = cv2.Canny(gray, 50, 150)

        # ---- combinar máscaras ----
        mask_combined = cv2.bitwise_or(mask_pink, mask_dark)

        # limpiar ruido
        kernel = np.ones((5,5), np.uint8)
        mask_combined = cv2.morphologyEx(mask_combined, cv2.MORPH_CLOSE, kernel)

    # ---- evaluación por ROI ----
    results_info = {}
    #count = []
    result_count = []
    for name, (x1, y1, x2, y2) in coords_array.items():
        x1, y1, x2, y2 = x1+offset_x, y1+offset_y, x2+offset_x, y2+offset_y
        roi_mask = mask_combined[y1:y2, x1:x2]
        roi_edges = edges[y1:y2, x1:x2]
        array_roi = [x1,y1,x2,y2]
        area_roi = cv2.contourArea(array_roi)
        area_total = roi_mask.size
        area_glue = cv2.countNonZero(roi_mask)
        ratio = area_glue / area_total
        # cv2.imshow("roi_mask", roi_mask)
        # cv2.imshow("roi_edges", roi_edges)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()
        # densidad de textura
        edge_density = np.count_nonzero(roi_edges) / roi_edges.size
        #cv2.rectangle(img_aux,(x1,y1),(x2,y2),(0, 255, 0), 8, 2)
        # ---- decisión ----
        if ratio > 0.15 or edge_density > 0.04:
            status = "OK"
            cv2.rectangle(img_aux,(x1,y1),(x2,y2),(0, 255, 0), 8, 2)
            result_count.append(1)
        else:
            status = "FAIL"
            cv2.rectangle(img_aux,(x1,y1),(x2,y2),(0, 0, 255), 8, 2)
            result_count.append(0)
        results_info[name] = {
            "ratio": ratio,
            "texture": edge_density,
            "status": status
        }
        #print(results)
    for roi, info in results_info.items():
        print(f"Zona: {roi}")
        print(f"  Ratio: {info['ratio']}")
        print(f"  Textura: {info['texture']}")
        print(f"  Estado: {info['status']}")
        print("-" * 20)
        
    print(result_count)
    print(f"Area del ROI en pixeles:{area_roi}")
    return result_count,results_info, img_aux


