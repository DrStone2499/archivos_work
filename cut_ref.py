import os
import cv2
import json 
from hsv import *
from static.config.settings import ROI_FILE, REF_PATH1, REF_PATH2
from resources.getOffset import *
from resources.TimInspect import *

path = 'resources/images/ErrFov'
#list_image = os.listdir(path)
lbls = ["Top_1", "Top_2"]
ref_paths = [REF_PATH1, REF_PATH2]
with open(ROI_FILE,"r") as f: data = json.load(f)
def timFunction(img,number,step):
    #components_list = data[lbls[number]]["Components_List"]
    
    try:
        #img = cv2.imread(path_image)
        #aux_img = img.copy()
        offset_x, offset_y = GetOffset(img, ref_paths[number],data['Ref_SearchZones'][number],data['Ref_Coords'][number])
    except Exception as e:
        print(e)

    print(offset_x,offset_y)
    coords_array = data[lbls[number]]
    #x1,y1,x2,y2 = coords[0]+offset_x, coords[1]+offset_y, coords[2]+offset_x, coords[3]+offset_y
    #img_cut = img[y1:y2,x1:x2]
    result_count,result_info, img_aux = hsvInspection(img,coords_array,offset_x, offset_y,step)
    #print(result)
    return result_count,result_info, img_aux
    #cv2.imwrite('resources/images/Ref_1.png', img_ref)


#print(list_image)
