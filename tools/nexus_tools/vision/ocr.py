# NEXUS OCR HELPER
from PIL import Image, ImageDraw
import os
from datetime import datetime

def get_text_element(result, search_text, image_path):
    """
    Finds a text element in EasyOCR results and returns its index.
    """
    found_index = None
    for index, element in enumerate(result):
        text = element[1].lower()
        if search_text.lower() in text:
            found_index = index
            break
            
    if found_index is not None:
        return found_index
    raise Exception(f"Text '{search_text}' not found in image.")

def get_text_coordinates(result, index, image_path):
    """
    Calculates center percentage coordinates for EasyOCR result at index.
    """
    if index >= len(result):
        raise Exception("OCR index out of range.")

    bounding_box = result[index][0]
    min_x = min([coord[0] for coord in bounding_box])
    max_x = max([coord[0] for coord in bounding_box])
    min_y = min([coord[1] for coord in bounding_box])
    max_y = max([coord[1] for coord in bounding_box])

    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    with Image.open(image_path) as img:
        width, height = img.size

    return {
        "x": round((center_x / width), 3),
        "y": round((center_y / height), 3)
    }
