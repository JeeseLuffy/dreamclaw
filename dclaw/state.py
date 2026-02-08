from typing import TypedDict, Annotated, List, Dict, Any, Optional
import operator

class AgentState(TypedDict):
    """
    State definition for the DClaw social agent.
    """
    # Core state
    messages: Annotated[List[str], operator.add]  # Appends messages to history
    
    # Emotion System
    emotion_vector: Dict[str, float]  # 6D vector: [Curiosity, Fatigue, Joy, Anxiety, Excitement, Frustration]
    
    # Constraints
    daily_token_budget: int  # Remaining budget for the day
    
    # Content Generation
    draft_content: Optional[str]  # Current content being drafted
    draft_candidates: List[str]  # Candidate drafts for best-of-n selection
    quality_score: float  # Critic score (0.0 - 1.0)
    critic_feedback: Optional[str]  # Reason from critic
    
    # Platform & Memory
    post_history: List[Dict[str, Any]]  # List of published posts
    memory_context: List[str] # Retrieved context from Mem0
    
    # Control flow
    next_step: Optional[str] # For conditional routing logic
