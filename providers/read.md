# Providers

External service provider integrations — 45+ model providers with health telemetry, capability registry, OAuth, and fallback routing.

**Version:** 2.0.0

## Provider List
OpenAI, Anthropic (Claude), Google Gemini, DeepSeek, Groq, Mistral, OpenRouter, Cohere, Together, Perplexity, Replicate, Fireworks, Sambanova, NVIDIA, xAI (Grok), Qwen, Azure OpenAI, HuggingFace, LM Studio, Ollama, llama.cpp, Zupra (offline CPU), and 25+ OpenAI-compatible providers via UniversalProvider.

## OAuth Providers
Codex (ChatGPT Plus/Pro), Claude, GitHub Copilot, Grok, Gemini, OpenRouter, Qwen, MiniMax, Chutes — all with PKCE + device code flows.

## Features
- Capability-aware provider fallback with normalized error handling
- Provider latency registry, health status API, auto-heal background thread
- OAuth 2.0 / PKCE / Device Code flows with token refresh
- ProviderProfileStore with cooldown, exponential backoff, and 3 rotation strategies
- Auto-detection of available providers via env vars and HTTP pings
- Factory pattern with 45+ provider mappings
