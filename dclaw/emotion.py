from typing import Dict, Any, Tuple
import math

class EmotionState:
    """
    Manages the agent's emotion using the PAD (Pleasure-Arousal-Dominance) model.
    This theoretical framework allows for continuous emotion dynamics and innovation in social simulation.
    
    The 6 basic emotions are mapped to the 3D PAD space:
    - Pleasure: Valence (Positive vs Negative)
    - Arousal: Activation level (Calm vs Excited)
    - Dominance: Control/Power (Submissive vs Dominant)
    """
    
    # PAD Mapping for discrete emotions (approximate centroids)
    # Range: -1.0 to 1.0
    PAD_MAPPING = {
        "Joy":        ( 0.8,  0.6,  0.7),
        "Curiosity":  ( 0.4,  0.5, -0.2), # Openness often implies slightly lower dominance/control in exploration
        "Excitement": ( 0.6,  0.8,  0.4),
        "Fatigue":    (-0.4, -0.7, -0.6), # Low arousal, low dominance
        "Anxiety":    (-0.5,  0.6, -0.4), # Negative valence, high arousal, low dominance
        "Frustration":(-0.6,  0.5,  0.6), # Negative valence, high arousal, high dominance (vs Anxiety)
    }

    def __init__(self, initial_state: Dict[str, float] = None, pad_state: Tuple[float, float, float] = None):
        self.discrete_vector = {
            "Joy": 0.5, "Curiosity": 0.5, "Excitement": 0.3,
            "Fatigue": 0.0, "Anxiety": 0.2, "Frustration": 0.1
        }
        if initial_state:
            self.discrete_vector.update(initial_state)
            
        # Initialize PAD state (Pleasure, Arousal, Dominance)
        # If not provided, derive from discrete vector
        if pad_state:
            self.pad = list(pad_state) # [P, A, D]
        else:
            self.pad = self._calculate_pad_from_discrete()

    def _calculate_pad_from_discrete(self) -> list:
        """Weighted average of discrete emotions to determine PAD state."""
        p, a, d = 0.0, 0.0, 0.0
        total_weight = sum(self.discrete_vector.values()) + 1e-9
        
        for emotion, weight in self.discrete_vector.items():
            ep, ea, ed = self.PAD_MAPPING.get(emotion, (0,0,0))
            p += ep * weight
            a += ea * weight
            d += ed * weight
            
        return [p/total_weight, a/total_weight, d/total_weight]

    def _update_discrete_from_pad(self):
        """
        Reverse mapping: Update discrete probabilities based on proximity in PAD space.
        This allows 'drifting' in PAD space to affect all emotions naturally.
        """
        curr_p, curr_a, curr_d = self.pad
        
        for emotion, (ep, ea, ed) in self.PAD_MAPPING.items():
            # Euclidean distance in PAD space
            dist = math.sqrt((curr_p - ep)**2 + (curr_a - ea)**2 + (curr_d - ed)**2)
            # Convert distance to similarity/weight (closer = higher)
            # Max possible dist is ~3.46 (sqrt(12)), so we normalize
            similarity = max(0.0, 1.0 - (dist / 2.0))
            self.discrete_vector[emotion] = round(similarity, 3)

    def update(self, event: str, intensity: float = 1.0):
        """
        Updates emotional state based on events, applying forces in PAD space.
        """
        # Event Impact Vectors (Delta P, A, D)
        event_impacts = {
            "browse_interesting": ( 0.2,  0.3,  0.0), # More pleasure, more arousal
            "browse_boring":      (-0.1, -0.4, -0.1), # Less pleasure, lower arousal
            "get_like":           ( 0.3,  0.2,  0.1), # Validation increases P and slightly D
            "get_reply":          ( 0.2,  0.4,  0.0), # Interaction is high arousal
            "post_ignored":       (-0.2, -0.1, -0.2), # Rejection hurts P and D
            "error":              (-0.3,  0.2, -0.3), # Frustrating but high arousal
            "reflection_positive": ( 0.1, -0.2,  0.1), # Calming positive thought
            "reflection_negative": (-0.1, -0.1, -0.1)
        }
        
        dp, da, dd = event_impacts.get(event, (0,0,0))
        
        self.pad[0] += dp * intensity
        self.pad[1] += da * intensity
        self.pad[2] += dd * intensity
        
        # Clamp to [-1.0, 1.0]
        self.pad = [max(-1.0, min(1.0, v)) for v in self.pad]
        
        # Sync discrete emotions
        self._update_discrete_from_pad()
        
        return self.discrete_vector

    def decay(self, factor: float = 0.1):
        """
        Simulates emotional decay towards a neutral baseline state (0, 0, 0).
        This implements the 'Emotional Inertia' innovation.
        """
        # Linear decay towards zero
        self.pad = [v * (1.0 - factor) for v in self.pad]
        self._update_discrete_from_pad()
        return self.discrete_vector

    def get_generation_params(self) -> Dict[str, Any]:
        """
        Maps PAD dimensions to LLM parameters.
        Innovation: Arousal -> Temperature, Pleasure -> Sentiment, Dominance -> Assertiveness.
        """
        p, a, d = self.pad
        
        # Temperature (Creativity) driven by Arousal
        # High arousal (Excited/Anxious) = Higher randomness/energy
        # Low arousal (Bored/Calm) = Deterministic/Repetitive
        temp = 0.4 + (0.5 * (a + 1.0) / 2.0) # Maps -1..1 to 0.4..0.9
        
        # Tone Analysis based on P and D
        if p > 0.3:
            tone = "enthusiastic" if a > 0.3 else "content"
        elif p < -0.3:
            tone = "frustrated" if d > 0.0 else "anxious" # High dominance neg = angry, low = fearful
        else:
            tone = "objective" if d > -0.2 else "apologetic"

        return {
            "temperature": round(temp, 2),
            "tone": tone,
            "pad": self.pad
        }
    
    def get_state(self) -> Dict[str, float]:
        return self.discrete_vector.copy()
