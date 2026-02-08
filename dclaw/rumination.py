from datetime import datetime
from typing import List, Dict, Any, Optional
import random

from .memory import AgentMemory
from .emotion import EmotionState

class RuminationEngine:
    """
    Handles the 'Autonomous Rumination' process during idle time.
    This simulates the 'Default Mode Network' of the brain.
    """
    def __init__(self, memory: AgentMemory, emotion_engine: EmotionState, llm_invoke=None):
        self.memory = memory
        self.emotion_engine = emotion_engine
        self.llm_invoke = llm_invoke

    def run_rumination_cycle(self, recent_memories: List[str]) -> Dict[str, Any]:
        """
        Executes one cycle of rumination:
        1. Reflect on recent memories + current emotion
        2. Generate an 'Insight'
        3. Shift Emotional Baseline
        4. Update Persona (optional)
        """
        if not recent_memories:
            return {"status": "no_memories", "insight": None}

        # 1. Synthesize Context
        context = "\n".join([f"- {m}" for m in recent_memories])
        current_pad = self.emotion_engine.pad
        
        # 2. Generate Insight via LLM
        insight = self._generate_insight(context, current_pad)
        
        # 3. Shift Baseline based on Insight Sentiment
        # (Simplified sentiment analysis for demo)
        sentiment_delta = self._analyze_sentiment_impact(insight)
        self.emotion_engine.pad[0] += sentiment_delta[0] * 0.1 # Accumulate baseline shift
        self.emotion_engine.pad[1] += sentiment_delta[1] * 0.1
        self.emotion_engine.pad[2] += sentiment_delta[2] * 0.1
        
        # Clamp baseline
        self.emotion_engine.pad = [max(-0.8, min(0.8, v)) for v in self.emotion_engine.pad]

        # 4. Store Insight
        self.memory.add_interaction(
            role="system",
            content=f"[RUMINATION INSIGHT] {insight}",
            metadata={"type": "insight", "source": "rumination"}
        )

        return {
            "status": "success",
            "insight": insight,
            "new_pad_baseline": self.emotion_engine.pad
        }

    def _generate_insight(self, context: str, pad: List[float]) -> str:
        prompt = (
            f"You are the inner voice of an AI. Reflect on these recent events:\n{context}\n\n"
            f"Current Emotional State (PAD): {pad}\n"
            "Analyze how these events affect your long-term outlook. "
            "Write one sentence starting with 'I realized that...' or 'I feel that...'"
        )
        if self.llm_invoke:
            return self.llm_invoke(prompt)
        
        # Fallback rule-based
        return "I realized distinct patterns in recent interactions that warrant caution."

    def _analyze_sentiment_impact(self, text: str) -> List[float]:
        # Mock sentiment analysis mapping to PAD delta
        # Real impl would use LLM or classifier
        text = text.lower()
        if "positive" in text or "good" in text or "excited" in text:
            return [0.2, 0.1, 0.1]
        if "negative" in text or "bad" in text or "sad" in text:
            return [-0.2, -0.1, -0.1]
        return [0.0, -0.05, 0.0] # Neutral/Calming
