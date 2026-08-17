# Bin

Bundled llama.cpp runtime binaries used for local LLM inference (Whisper STT, LLM serving, tooling).

**Version:** 2.0.0

## Contents
`bin/llama.cpp/` contains only the llama.cpp runtime:

- **30 DLLs** — `ggml-base.dll`, `ggml.dll`, `llama.dll`, `mtmd.dll`, `libomp140.x86_64.dll`, plus per-microarchitecture `ggml-cpu-*` variants (sse42, x64, sandybridge, ivybridge, haswell, cascadelake, cooperlake, skylakex, icelake, alderlake, cannonlake, sapphirerapids, piledriver, zen4), `ggml-vulkan.dll`, `ggml-rpc.dll`, and per-tool `*-impl.dll` libs
- **22 EXEs** — `llama-cli.exe`, `llama-server.exe`, `llama-bench.exe`, `llama-batched-bench.exe`, `llama-quantize.exe`, `llama-perplexity.exe`, `llama-tts.exe`, `llama-tokenize.exe`, `llama-imatrix.exe`, `llama-gguf-split.exe`, `llama-completion.exe`, `llama-fit-params.exe`, `llama-gemma3-cli.exe`, `llama-llava-cli.exe`, `llama-minicpmv-cli.exe`, `llama-mtmd-cli.exe`, `llama-mtmd-debug.exe`, `llama-qwen2vl-cli.exe`, `llama-results.exe`, `llama-template-analysis.exe`, `llama.exe`, `rpc-server.exe`
