# NEXUS AI: Sovereign Engineering Project Memory (A to Z)

This document is the definitive technical record of the NEXUS AI platform. It captures the entire architecture and the "Dominance Upgrades" implemented to achieve absolute technical superiority.

---

## 🏛️ A to Z Architecture Breakdown

### **A. The Sovereign Kernel (`kernel/` package)**
The heart of the system. A thread-safe singleton that manages lazy-loading for all core services:
*   **MoE Router:** Dynamic model tiering (NANO to EXTREME).
*   **Hive Engine:** Asynchronous Hive worker orchestration.
*   **RAG Engine:** Long-term vector memory.
*   **Tool Registry:** Hardened access to bash, files, git, and more.

### **B. Unified Cognitive Loop (`orchestrators/loop.py`)**
A single-stage execution loop inspired by Claude Code and OpenClaw:
*   **Grounding:** Unified assembly of codebase maps, memories, and failures.
*   **Reasoning:** Recursive DAG planning via the Architect.
*   **Action:** Parallel read/serial write tool execution.
*   **Learning:** Real-time Neural Backprop (Experience Replay).

### **C. Efficiency & Token Savings**
*   **NexusContextCompressor:** LLM-driven high-fidelity history compaction.
*   **Zero-Token Context Engine:** Replaces large text with ID pointers + 900-char summaries.
*   **Dynamic Protocol Injection:** Only includes complex instructions (Self-Correction/Improvement) when necessary.

---

## 🛠️ Implemented Dominance Upgrades (A to Z)

1.  **🚀 Recursive DAG Architect:** Decomposes missions into technical sub-goal graphs with logical dependencies.
2.  **Async Hive Kernel:** Non-blocking task execution allowing 10+ Hive workers to operate in parallel.
3.  **🧠 Active Experience Replay:** Immediate strategy adjustment and memory graph updates following tool failures.
4.  **🔗 Knowledge Graph Reasoning:** Multi-hop semantic traversal linking failures to historical project context.
5.  **🏗️ Architectural Foresight:** Real-time cross-file dependency scanning after every file edit.
6.  **🛡️ Unified Cognitive Grounding:** Single-pass deduplicated injection of RAG and Graph facts.
7.  **👁️ Multi-modal Vision Grounding:** Image/UI analysis bridge for layout auditing.
8.  **🧬 Neural Self-Distillation:** Automatic collection of "Gold Standard" interactions for GGUF fine-tuning.
9.  **🛡️ Sovereign Sandbox Execution:** 2-tier security (Restricted Shell / Docker) with risk-based filtering.

---

## 🛡️ Security & Autonomy Configuration

### **Autonomy Modes**
*   **AUTO_PILOT (Default):** Agent self-governs; blocks only high-risk commands.
*   **BYPASS:** Sovereign mode; no blocks, maximum speed.
*   **APPROVE:** Manual control; prompts for every action.
*   **PRE_AUTHORIZED:** Whitelist mode; only runs saved/approved commands.

### **Sandbox Tiers**
*   **NO_SANDBOX (Default):** Direct speed.
*   **SANDBOX:** Isolation via **Normal** (Shell) or **Docker** backends.

---

## 🧠 Memory Persistence
*   **Session Context:** Automatically saved to `logs/sessions/` and reloaded on start.
*   **Global History:** Permanent record in `logs/memory/global_history.md`.
*   **Impact Sensing:** `ARCHITECTURAL_IMPACT_SCAN` active on all file edits.

**NEXUS AI is now the benchmark for autonomous engineering. This memory file ensures continuity across all future sessions.**
