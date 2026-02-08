from dclaw.graph import build_graph
from dclaw.config import AgentConfig
import uuid

def test_workflow():
    print("Initializing Graph...")
    app = build_graph(
        AgentConfig(
            use_llm_generation=False,
            use_prompt_critic=False,
            use_real_mem0=False,
            candidate_drafts=2,
            max_posts_per_day=1,
        )
    )
    
    # Initial State
    initial_state = {
        "messages": [],
        "emotion_vector": {
            "Curiosity": 0.5, "Fatigue": 0.0, "Joy": 0.5, 
            "Anxiety": 0.2, "Excitement": 0.3, "Frustration": 0.1
        },
        "daily_token_budget": 600,
        "draft_content": None,
        "draft_candidates": [],
        "quality_score": 0.0,
        "critic_feedback": None,
        "post_history": [],
        "memory_context": [],
        "next_step": None
    }
    
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    
    print(f"\nStarting workflow with thread_id: {config['configurable']['thread_id']}")
    
    # Run the graph
    for event in app.stream(initial_state, config=config):
        for node, values in event.items():
            print(f"\nFinished Node: {node}")
            # print(f"State Update: {values}")

if __name__ == "__main__":
    test_workflow()
