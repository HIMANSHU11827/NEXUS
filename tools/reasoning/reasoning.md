# Reasoning Tool
**Version:** 2.0.0 — upgraded with problem decomposition, uncertainty estimation, and verification.

Performs deep chain-of-thought reasoning with problem-specific decomposition strategies.

## Parameters
- `problem` (string, required): Problem to reason about
- `depth` (string, optional, default=detailed): simple | detailed | deep
- `steps` (int, optional, default=5): Maximum reasoning steps
- `context` (string, optional): Additional context for reasoning

## Features
- **Smart decomposition**: debug, design, and analyze problem types with tailored analysis steps
- **Uncertainty estimation**: each step rated Low/Medium/High uncertainty
- **Alternative consideration**: multiple approaches evaluated when relevant
- **Synthesis**: key findings summarized across all steps
- **Verification**: final quality check with uncertainty assessment
