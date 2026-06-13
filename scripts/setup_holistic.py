import subprocess
import sys
import os
import shutil


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_DIR = os.path.join(ROOT, "gui")
LOCAL_MODEL_DIR = os.path.join(ROOT, "models", "local", "mediapipe", "holistic")
DASHBOARD_ASSET_DIR = os.path.join(DASHBOARD_DIR, "public", "mediapipe", "holistic")


def _run(cmd, cwd=None):
    if os.name == "nt" and cmd and cmd[0] == "npm":
        cmd = ["npm.cmd", *cmd[1:]]
    print("[cmd]", " ".join(cmd))
    subprocess.check_call(cmd, cwd=cwd)


def _copy_tree_files(src, dst, suffixes=None):
    if not os.path.isdir(src):
        return 0
    os.makedirs(dst, exist_ok=True)
    copied = 0
    for name in os.listdir(src):
        path = os.path.join(src, name)
        if not os.path.isfile(path):
            continue
        if suffixes and not any(name.endswith(suffix) for suffix in suffixes):
            continue
        shutil.copy2(path, os.path.join(dst, name))
        copied += 1
    return copied


def vendor_dashboard_assets():
    """Copy official @mediapipe/holistic runtime files into local gui/public."""
    package_dir = os.path.join(DASHBOARD_DIR, "node_modules", "@mediapipe", "holistic")
    suffixes = (".js", ".wasm", ".binarypb", ".tflite", ".data")
    copied_public = _copy_tree_files(package_dir, DASHBOARD_ASSET_DIR, suffixes)
    copied_model = _copy_tree_files(package_dir, os.path.join(LOCAL_MODEL_DIR, "web_assets"), suffixes)
    for package_name, filename in (
        ("camera_utils", "camera_utils.js"),
        ("drawing_utils", "drawing_utils.js"),
    ):
        src = os.path.join(DASHBOARD_DIR, "node_modules", "@mediapipe", package_name)
        public_dst = os.path.join(DASHBOARD_DIR, "public", "mediapipe", package_name)
        model_dst = os.path.join(LOCAL_MODEL_DIR, "web_assets", package_name)
        copied_public += _copy_tree_files(src, public_dst, (filename,))
        copied_model += _copy_tree_files(src, model_dst, (filename,))
    return copied_public, copied_model

def setup():
    print("[*] Setting up MediaPipe Holistic for NEXUS AI...")
    
    # Install Python packages for official MediaPipe APIs.
    try:
        _run([sys.executable, "-m", "pip", "install", "-e", ".[vision]"], cwd=ROOT)
        print("[+] Python vision dependencies installed.")
    except Exception as e:
        print(f"[!] Error installing MediaPipe: {e}")
        print("[!] Continuing with gui asset setup.")

    # Install official MediaPipe web packages and save them into package.json.
    try:
        _run([
            "npm",
            "install",
            "@mediapipe/holistic",
            "@mediapipe/drawing_utils",
            "@mediapipe/camera_utils",
            "--save",
        ], cwd=DASHBOARD_DIR)
        copied_public, copied_model = vendor_dashboard_assets()
        print(f"[+] Vendored {copied_public} gui files to {DASHBOARD_ASSET_DIR}.")
        print(f"[+] Saved {copied_model} local model/runtime files to {LOCAL_MODEL_DIR}.")
    except Exception as e:
        print(f"[!] gui MediaPipe asset setup failed: {e}")

    # Warm up: download models
    print("[*] Warming up Holistic models...")
    try:
        import mediapipe as mp
        import cv2
        import numpy as np

        if not hasattr(mp, "solutions"):
            raise RuntimeError(
                "Installed mediapipe package does not expose mp.solutions. "
                "The gui integration is still usable with vendored web assets."
            )
        mp_holistic = mp.solutions.holistic
        with mp_holistic.Holistic(static_image_mode=True) as holistic:
            # Create a black image to trigger model loading
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            holistic.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        print("[+] Holistic models are ready.")
    except Exception as e:
        print(f"[!] Warmup failed: {e}")

if __name__ == "__main__":
    setup()
