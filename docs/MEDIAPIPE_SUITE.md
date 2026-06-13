# MediaPipe Suite

NEXUS connects Google MediaPipe through two local paths:

- Real-time Holistic webcam tracking uses the official vendored web runtime in `gui/public/mediapipe`.
- Python task runners use local model files in `models/local/mediapipe/tasks`.

## gui Runtime Status

The Vision gui keeps every MediaPipe capability visible, but the labels mean different things:

- `LIVE`: works in the webcam gui now and can be turned on/off.
- `READY`: model files are downloaded locally, but the live webcam runner is not wired into the gui yet.
- `SLOT`: NEXUS knows the capability, but it still needs a compatible model file, runner wiring, or both.

### Truly Live Today

| Capability | gui behavior |
| --- | --- |
| Body tracking | Live Holistic pose overlay |
| Face tracking | Live Holistic face mesh overlay |
| Hand tracking | Live Holistic hand overlay |
| Full body + face + hands | Live Holistic combined pipeline |
| Image segmentation | Live Holistic person mask overlay |

### Model-Ready, Not Live Webcam Yet

| Capability | Local model status | Next work |
| --- | --- | --- |
| Object detection | EfficientDet-Lite0 downloaded | Wire browser or backend frame runner |
| Gesture recognition | Gesture Recognizer downloaded | Wire hand crop/frame runner |
| Image classification | EfficientNet-Lite0 downloaded | Wire frame classifier |
| Face detection | BlazeFace short range downloaded | Backend task model ready |
| Face tracking | Face Landmarker downloaded | Backend task model ready |
| Hand tracking | Hand Landmarker downloaded | Backend task model ready |
| Body tracking | Pose Landmarker Lite downloaded | Backend task model ready |

### Slots, Runner/Model Pending

| Capability | Status |
| --- | --- |
| Hair segmentation | Graph exists in source; gui runner not wired |
| Image embedding/search | Needs compatible embedder model and runner |
| Audio classification | Needs audio capture/tensor runner |
| Text classification | Needs compatible model and text UI/runner |
| Text embedding | Needs compatible model and text UI/runner |
| Language detection | Needs compatible model and text UI/runner |
| LLM/GenAI edge tasks | Tracked as future MediaPipe GenAI capability |

## Connected Backend Capabilities

| Capability | MediaPipe Task | Status |
| --- | --- | --- |
| Body tracking | Pose Landmarker | Model downloaded; gui uses Holistic live path |
| Face tracking | Face Landmarker | Model downloaded; gui uses Holistic live path |
| Hand tracking | Hand Landmarker | Model downloaded; gui uses Holistic live path |
| Full body + face + hands | Holistic | Connected through gui webcam runtime |
| Image segmentation | Image Segmenter | Selfie model downloaded; gui uses Holistic mask live path |
| Object detection | Object Detector | EfficientDet-Lite0 downloaded; not live in gui yet |
| Gesture recognition | Gesture Recognizer | Model downloaded; not live in gui yet |
| Image classification | Image Classifier | EfficientNet-Lite0 downloaded; not live in gui yet |
| Image embedding/search | Image Embedder | Slot only; needs compatible model file |
| Audio classification | Audio Classifier | Slot only; audio tensor runner pending |
| Text classification | Text Classifier | Slot only; needs compatible model file |
| Text embedding | Text Embedder | Slot only; needs compatible model file |
| Language detection | Language Detector | Slot only; needs compatible model file |
| LLM/GenAI edge tasks | MediaPipe GenAI | Tracked as capability; NEXUS model routing remains primary |

## Performance Notes

The gui defaults to an optimized adaptive webcam path:

- It starts with practical camera profiles, then falls back to basic `video: true` if a webcam rejects constraints.
- It avoids desktop-hostile `facingMode` constraints and can retry camera startup from the error panel.
- It installs a high-performance WebGL context preference before MediaPipe loads, so Chrome is asked to use the iGPU/GPU path instead of low-power rendering.
- It reports the active WebGL renderer in the Vision panel and warns if Chrome falls back to software rendering such as SwiftShader.
- Body, Face, Hands, and Image Seg toggles control their own overlays independently; Holistic acts as a group toggle for Body + Face + Hands.
- It uses the lite Holistic model by default to reduce lag.
- It keeps the real webcam video as the background layer and draws landmarks on a separate overlay canvas, so the live camera view does not wait for model inference.
- It starts the webcam before loading the tracker, so camera preview remains visible even if MediaPipe fails.
- It reports camera permission/device/constraint failures in the Vision panel instead of hiding them behind a black screen.
- It uses browser video-frame callbacks when available, so inference follows real camera frames instead of display refresh ticks.
- It watches missed/slow frames, slows inference briefly when processing becomes expensive, then recovers when the machine catches up.
- It keeps Holistic in video tracking mode with smoothing enabled and lower tracking confidence, so fast motion does not constantly force expensive re-detection.
- There is no separate camera, speed, or quality toggle in the UI; adaptation is automatic.

## Native iGPU Backend Plan

NEXUS now has a `vision_accelerator` probe that reports real backend GPU readiness instead of guessing.

- Preferred native path for this machine: OpenVINO GPU/AUTO on Intel UHD Graphics.
- Windows fallback path: ONNX Runtime DirectML for ONNX models on Intel/AMD/NVIDIA GPUs.
- Current gui live path: MediaPipe Holistic web runtime, accelerated by browser WebGL when Chrome hardware acceleration is active.
- Current Python environment: OpenVINO 2026 and ONNX Runtime DirectML are installed; the accelerator probe selects OpenVINO GPU when Intel iGPU is visible.

Important distinction: browser Holistic and backend native inference are different paths. The gui can use WebGL today, but true backend iGPU runners need OpenVINO or DirectML plus compatible models converted or exported for those runtimes.

Use the NEXUS tool `vision_accelerator` or the gui API:

```powershell
python -c "from tools.nexus_tools.vision.vision_accelerator_tool import VisionAccelerator; import json; print(json.dumps(VisionAccelerator().status(), indent=2))"
```

```text
GET http://127.0.0.1:8000/api/vision/accelerator
```

## Tool

Use the NEXUS tool `mediapipe_suite`.

Actions:

- `status`: show installed MediaPipe version, importability, local model paths, and model presence.
- `capabilities`: list all connected task specs.
- `download_model`: download one known model into `models/local/mediapipe/tasks`.
- `download_all`: download all known official model URLs.
- `run`: run a supported image or text task with `image_path` or `text`.

Example:

```powershell
python scripts\setup_mediapipe_suite.py
```

This refreshes Holistic gui assets and downloads all known official task models.

## Important Runtime Note

The installed `mediapipe 0.10.33` package on this machine exposes the newer Tasks modules, but does not expose the older `mp.solutions` API. NEXUS therefore uses direct task module imports for Python tasks and the vendored official JavaScript Holistic runtime for live 543-landmark webcam tracking.
