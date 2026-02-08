from typing import Dict, Any

class EmotionState:
    """
    Manages the 6-dimensional emotion vector for the agent.
    Dimensions: Curiosity, Fatigue, Joy, Anxiety, Excitement, Frustration
    Range: 0.0 to 1.0
    """
    def __init__(self, initial_state: Dict[str, float] = None):
        default_state = {
            "Curiosity": 0.5,
            "Fatigue": 0.0,
            "Joy": 0.5,
            "Anxiety": 0.2,
            "Excitement": 0.3,
            "Frustration": 0.1
        }
        self.vector = initial_state if initial_state else default_state
        self._normalize()

    def _normalize(self):
        """Ensure all values stay within 0.0 - 1.0 range."""
        for key in self.vector:
            self.vector[key] = max(0.0, min(1.0, self.vector[key]))

    def update(self, event: str, intensity: float = 1.0):
        """
        Updates emotion state based on an event.
        Events: browse_interesting, browse_boring, get_like, get_reply, post_ignored, error
        """
        # Delta mappings (emotion, change)
        emotion_mapping = {
            "browse_interesting": {"Curiosity": +0.1, "Joy": +0.05, "Fatigue": -0.05},
            "browse_boring": {"Fatigue": +0.1, "Curiosity": -0.05, "Frustration": +0.05},
            "get_like": {"Joy": +0.1, "Excitement": +0.1, "Frustration": -0.05},
            "get_reply": {"Joy": +0.15, "Curiosity": +0.05, "Anxiety": +0.02}, # Replies can be anxious
            "post_ignored": {"Frustration": +0.1, "Fatigue": +0.05, "Excitement": -0.1},
            "error": {"Frustration": +0.2, "Anxiety": +0.1}
        }
        
        changes = emotion_mapping.get(event, {})
        for emotion, delta in changes.items():
            if emotion in self.vector:
                self.vector[emotion] += delta * intensity
        
        self._normalize()
        return self.vector

    def get_generation_params(self) -> Dict[str, Any]:
        """
        Maps current emotions to LLM generation parameters.
        """
        # Temperature: correlated with Curiosity and Excitement
        # Curiosity drives exploration (higher temp), Fatigue drives safety (lower temp)
        temp = 0.5 + (0.4 * self.vector["Curiosity"]) + (0.2 * self.vector["Excitement"]) - (0.3 * self.vector["Fatigue"])
        temp = max(0.1, min(1.0, temp)) # Clamp between 0.1 and 1.0
        
        # Tone determination
        if self.vector["Frustration"] > 0.6:
            tone = "critical"
        elif self.vector["Joy"] > 0.6 or self.vector["Excitement"] > 0.6:
            tone = "enthusiastic"
        elif self.vector["Anxiety"] > 0.6:
            tone = "cautious"
        elif self.vector["Fatigue"] > 0.7:
            tone = "tired/minimalist"
        else:
            tone = "objective"
            
        return {
            "temperature": round(temp, 2),
            "tone": tone
        }

    def get_state(self) -> Dict[str, float]:
        return self.vector.copy()
