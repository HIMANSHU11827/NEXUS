import io
import base64
import os
import time
from PIL import Image, ImageDraw

def get_label_coordinates(label, label_coordinates):
    """Retrieves the coordinates for a given label (~1, ~2, etc)."""
    return label_coordinates.get(label)

def is_overlapping(box1, box2):
    """Checks if two bounding boxes overlap."""
    x1_box1, y1_box1, x2_box1, y2_box1 = box1
    x1_box2, y1_box2, x2_box2, y2_box2 = box2
    if x1_box1 > x2_box2 or x1_box2 > x2_box1:
        return False
    if y1_box1 > y2_box2 or y1_box2 > y2_box1:
        return False
    return True

def add_labels(base64_data, yolo_model):
    """Adds interactive labels to a screenshot using YOLO detections."""
    image_bytes = base64.b64decode(base64_data)
    image = Image.open(io.BytesIO(image_bytes))
    image_labeled = image.copy()
    
    results = yolo_model(image_labeled)
    draw = ImageDraw.Draw(image_labeled)
    font_size = 40
    
    label_coordinates = {}
    counter = 0
    drawn_boxes = []
    
    for result in results:
        if hasattr(result, "boxes"):
            for det in result.boxes:
                bbox = det.xyxy[0]
                x1, y1, x2, y2 = bbox.tolist()
                
                # Check for overlap to prevent clutter
                overlap = any(is_overlapping((x1, y1, x2, y2), box) for box in drawn_boxes)
                
                if not overlap:
                    draw.rectangle([(x1, y1), (x2, y2)], outline="red", width=2)
                    label = f"~{counter}"
                    draw.text((x1, y1 - font_size), label, fill="red")
                    
                    drawn_boxes.append((x1, y1, x2, y2))
                    label_coordinates[label] = (x1, y1, x2, y2)
                    counter += 1

    buffered = io.BytesIO()
    image_labeled.save(buffered, format="PNG")
    img_b64_labeled = base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    return img_b64_labeled, label_coordinates

def get_click_position_in_percent(coordinates, image_size):
    """Utility to calculate center click position in screen percentage."""
    if not coordinates or not image_size: return None
    x_center = (coordinates[0] + coordinates[2]) / 2
    y_center = (coordinates[1] + coordinates[3]) / 2
    return (x_center / image_size[0]), (y_center / image_size[1])
