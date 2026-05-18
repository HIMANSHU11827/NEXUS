from PIL import Image

def resize_image(path, size):
    img = Image.open(path)
    img = img.resize(size)
    img.save(path)