"""Perception Layer - Multi-modal input processing for NEXUS V5.

This layer handles:
- Multi-modal input processing (text, voice, vision, code)
- Intent recognition
- Context fusion
- Attention mechanism
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import re

logger = logging.getLogger(__name__)


class InputType(str, Enum):
    """Types of input the perception layer can handle."""
    TEXT = "text"
    VOICE = "voice"
    VISION = "vision"
    CODE = "code"
    MULTIMODAL = "multimodal"


class Intent(str, Enum):
    """Recognized user intents."""
    CHAT = "chat"
    TASK = "task"
    RESEARCH = "research"
    CODING = "coding"
    DEBUGGING = "debugging"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    UNKNOWN = "unknown"


@dataclass
class PerceivedInput:
    """Result of perception processing."""
    original_input: str
    input_type: InputType
    intent: Intent
    confidence: float
    extracted_entities: Dict[str, Any] = field(default_factory=dict)
    context_summary: str = ""
    attention_weights: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PerceptionLayer:
    """Perception layer for multi-modal input processing."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.logger = logging.getLogger("nexus.v5.perception")
        
        # Intent patterns
        self.intent_patterns = {
            Intent.CODING: [
                r"\b(code|function|class|def|import|bug|fix|implement)\b",
                r"\b(write|create|edit|modify|refactor)\s+(code|function|class)\b",
            ],
            Intent.RESEARCH: [
                r"\b(search|find|research|look up|investigate)\b",
                r"\b(what|how|why|when|where|who)\b",
            ],
            Intent.TASK: [
                r"\b(do|execute|run|perform|complete)\b",
                r"\b(task|job|work)\b",
            ],
            Intent.DEBUGGING: [
                r"\b(debug|error|issue|problem|fix|troubleshoot)\b",
                r"\b(not working|failing|broken)\b",
            ],
            Intent.ANALYSIS: [
                r"\b(analyze|review|examine|evaluate)\b",
                r"\b(summary|overview|breakdown)\b",
            ],
            Intent.CREATIVE: [
                r"\b(write|create|generate|compose)\b",
                r"\b(story|poem|article|content)\b",
            ],
        }

    async def process(self, turn: Any) -> PerceivedInput:
        """Process input through perception layer.
        
        Args:
            turn: V5TurnContext instance
        
        Returns:
            PerceivedInput with processed information
        """
        input_type = InputType(turn.input_type)
        original_input = turn.user_input
        
        # Recognize intent
        intent, confidence = self._recognize_intent(original_input)
        
        # Extract entities
        entities = self._extract_entities(original_input, intent)
        
        # Generate context summary
        context_summary = self._generate_context_summary(original_input, intent)
        
        # Compute attention weights
        attention_weights = self._compute_attention_weights(original_input)
        
        perceived = PerceivedInput(
            original_input=original_input,
            input_type=input_type,
            intent=intent,
            confidence=confidence,
            extracted_entities=entities,
            context_summary=context_summary,
            attention_weights=attention_weights,
            metadata={"turn_id": turn.turn_id}
        )
        
        self.logger.info(f"Perceived input: intent={intent.value}, confidence={confidence:.2f}")
        return perceived

    def _recognize_intent(self, text: str) -> tuple[Intent, float]:
        """Recognize user intent from text."""
        text_lower = text.lower()
        
        intent_scores = {intent: 0.0 for intent in Intent}
        
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                matches = len(re.findall(pattern, text_lower))
                intent_scores[intent] += matches
        
        # Normalize scores
        total_matches = sum(intent_scores.values())
        if total_matches == 0:
            return Intent.CHAT, 0.5
        
        # Find best intent
        best_intent = max(intent_scores, key=intent_scores.get)
        confidence = min(intent_scores[best_intent] / total_matches, 1.0)
        
        return best_intent, confidence

    def _extract_entities(self, text: str, intent: Intent) -> Dict[str, Any]:
        """Extract entities from text based on intent."""
        entities = {}
        
        # Common entity patterns
        file_pattern = r'["\']?([a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+)["\']?'
        files = re.findall(file_pattern, text)
        if files:
            entities["files"] = files
        
        # Code patterns
        if intent == Intent.CODING:
            function_pattern = r'\b(def|class|function)\s+(\w+)'
            functions = re.findall(function_pattern, text)
            if functions:
                entities["functions"] = [f[1] for f in functions]
        
        # URLs
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, text)
        if urls:
            entities["urls"] = urls
        
        # Numbers/quantities
        number_pattern = r'\b(\d+)\b'
        numbers = re.findall(number_pattern, text)
        if numbers:
            entities["numbers"] = numbers
        
        return entities

    def _generate_context_summary(self, text: str, intent: Intent) -> str:
        """Generate a summary of the context."""
        # Simple summary based on intent and length
        if len(text) > 500:
            summary = text[:200] + "..." + text[-100:]
        else:
            summary = text
        
        return f"[{intent.value.upper()}] {summary}"

    def _compute_attention_weights(self, text: str) -> Dict[str, float]:
        """Compute attention weights for different parts of text."""
        words = text.split()
        if not words:
            return {}
        
        # Simple TF-based attention
        word_freq = {}
        for word in words:
            word_lower = word.lower()
            word_freq[word_lower] = word_freq.get(word_lower, 0) + 1
        
        total_words = len(words)
        attention_weights = {
            word: freq / total_words 
            for word, freq in word_freq.items()
        }
        
        # Normalize
        max_weight = max(attention_weights.values()) if attention_weights else 1
        attention_weights = {
            k: v / max_weight 
            for k, v in attention_weights.items()
        }
        
        return attention_weights
