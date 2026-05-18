import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def setup(download: bool = True):
    print("[*] Connecting MediaPipe suite assets for NEXUS AI...")

    try:
        from scripts.setup_holistic import vendor_dashboard_assets

        copied_public, copied_model = vendor_dashboard_assets()
        print(f"[+] Holistic dashboard files vendored: {copied_public}")
        print(f"[+] Holistic local runtime files saved: {copied_model}")
    except Exception as exc:
        print(f"[!] Holistic asset vendoring failed: {exc}")

    from tools.nexus_tools.vision.mediapipe_suite_tool import MediaPipeSuiteTool

    tool = MediaPipeSuiteTool()
    status = tool.status()
    print("[+] MediaPipe installed:", status["mediapipe"].get("installed"))
    print("[+] MediaPipe version:", status["mediapipe"].get("version"))

    if download:
        print("[*] Downloading known official MediaPipe task models...")
        results = tool.download_all()
        for key, result in results.items():
            if result.get("downloaded"):
                print(f"[+] {key}: {result['local_model_path']} ({result['bytes']} bytes)")
            else:
                print(f"[-] {key}: {result.get('reason')}")

    return tool.status()


if __name__ == "__main__":
    setup(download="--no-download" not in sys.argv)
