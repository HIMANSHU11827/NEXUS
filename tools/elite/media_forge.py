import subprocess

def process_media(args):
    # args: list of ffmpeg arguments
    return subprocess.run(["ffmpeg"] + args, capture_output=True, text=True)