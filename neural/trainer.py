"""NexusTrainer — truthful training-capability facade.

The neural package does not bundle PyTorch.  NexusTrainer therefore exposes
configuration validation and a status API, and raises a clear, actionable
error when actual training is attempted without the torch backend.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NEXUS_TRAINER")

_TORCH_IMPORT_ERROR: Optional[str] = None
try:
    import torch  # noqa: F401
except Exception as exc:  # pragma: no cover - environment dependent
    _TORCH_IMPORT_ERROR = str(exc) or type(exc).__name__


class NexusTrainer:
    """Validate training configs and report training capability.

    No fake success: status() reports whether torch is available and
    train() refuses with a truthful error when it cannot actually train.
    """

    def __init__(self, root: str):
        self.root = os.path.abspath(root or ".")
        self.framework = "torch"
        self._torch_available = _TORCH_IMPORT_ERROR is None
        logger.info("NexusTrainer initialized (framework=%s, torch=%s)", self.framework, self._torch_available)

    # ------------------------------------------------------------------ capability

    @property
    def torch_available(self) -> bool:
        """True when the torch backend can actually be imported."""
        return self._torch_available

    def available(self) -> bool:
        """Report whether training infrastructure is present (torch)."""
        return self._torch_available

    def status(self) -> Dict[str, Any]:
        """Return a truthful capability snapshot for diagnostics/UI."""
        return {
            "available": self._torch_available,
            "framework": self.framework,
            "torch_installed": self._torch_available,
            "torch_import_error": _TORCH_IMPORT_ERROR,
            "model_training": "not_implemented",
            "root": self.root,
            "note": "NexusTrainer validates configs and reports status; real training requires torch.",
        }

    def capabilities(self) -> Dict[str, Any]:
        """Return the list of supported operations (truthful subset)."""
        ops = ["validate_config", "status"]
        if self._torch_available:
            ops.append("train")
        return {"operations": ops, "torch_installed": self._torch_available}

    # ------------------------------------------------------------------ config

    def validate_config(self, config: Optional[dict] = None) -> Dict[str, Any]:
        """Validate a training config without attempting to train.

        Returns {"valid": bool, "errors": [...]}.  No training is performed.
        """
        errors: List[str] = []
        cfg = config if isinstance(config, dict) else {}
        model_type = cfg.get("model_type")
        if not model_type or not isinstance(model_type, str) or not model_type.strip():
            errors.append("config[model_type] must be a non-empty string")
        epochs = cfg.get("epochs")
        if epochs is not None:
            try:
                if int(epochs) < 1:
                    errors.append("config[epochs] must be >= 1")
            except (TypeError, ValueError):
                errors.append("config[epochs] must be an integer")
        learning_rate = cfg.get("learning_rate")
        if learning_rate is not None:
            try:
                if float(learning_rate) <= 0:
                    errors.append("config[learning_rate] must be > 0")
            except (TypeError, ValueError):
                errors.append("config[learning_rate] must be a number")
        return {
            "valid": not errors,
            "errors": errors,
            "framework": self.framework,
            "torch_installed": self._torch_available,
        }

    # ------------------------------------------------------------------ training

    def train(self, config: Optional[dict] = None, **kwargs) -> Any:
        """Refuse to train with a truthful, actionable error.

        Raises RuntimeError when torch is missing and NotImplementedError when
        torch exists but no training pipeline is configured.  Never fakes
        a successful training run.
        """
        if not self._torch_available:
            raise RuntimeError(
                "NexusTrainer cannot train: the torch package is not installed in this "
                "environment. Install torch to enable model training.",
            )
        raise NotImplementedError(
            "NexusTrainer does not implement a training pipeline yet; use "
            "validate_config()/status() to check capability.",
        )


__all__ = ["NexusTrainer"]
