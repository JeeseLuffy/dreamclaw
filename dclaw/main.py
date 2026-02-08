import uuid
import time
import argparse
from dclaw.graph import build_graph
from dclaw.config import AgentConfig

def run_agent(mode="interactive", thread_id=None):
    print(f"Starting DClaw Agent in {mode} mode...")
    config_obj = AgentConfig.from_env()
    app = build_graph(config_obj)
    
    if not thread_id:
        thread_id = str(uuid.uuid4())
        
    config = {"configurable": {"thread_id": thread_id}}
    
    # Initial State
    initial_state = {
        "messages": [],
        "emotion_vector": {
            "Curiosity": 0.5, "Fatigue": 0.0, "Joy": 0.5, 
            "Anxiety": 0.2, "Excitement": 0.3, "Frustration": 0.1
        },
        "daily_token_budget": config_obj.max_tokens_per_day,
        "draft_content": None,
        "draft_candidates": [],
        "quality_score": 0.0,
        "critic_feedback": None,
        "post_history": [],
        "memory_context": [],
        "next_step": None,
    }

    try:
        # For demo purposes, we run one cycle. 
        # In daemon mode, this would be a loop with sleep.
        print(f"Session ID: {thread_id}")
        
        # Determine input based on if it's a resume or fresh start
        # If resuming, we ideally pass None to continue from current state,
        # but LangGraph stream expects input for start node if not provided.
        # For simplicity, we restart with initial state but checkpointer keeps history.
        
        inputs = None if mode == "resume" else initial_state
        
        # If input is None, we need to know the next node or just let it resume.
        # langgraph's app.stream(None, config) resumes.
        
        if mode == "daemon":
            while True:
                print(f"\n[{time.strftime('%X')}] Waking up agent...")
                for event in app.stream(initial_state if inputs else None, config=config):
                    for node, values in event.items():
                        print(f"Processed Node: {node}")
                
                print(f"[{time.strftime('%X')}] Sleeping for 10 seconds...")
                time.sleep(10)
                inputs = None # subsequent runs resume? 
                # Actually, cyclic graph ends at 'post' -> END. 
                # So next loop starts fresh but with persisted state if we handle it.
                # Here we arguably want start a NEW cycle.
                
        else:
             for event in app.stream(initial_state, config=config):
                for node, values in event.items():
                    print(f"Processed Node: {node}")
                    
    except KeyboardInterrupt:
        print("\nStopping Agent...")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DClaw Agent")
    parser.add_argument("--mode", type=str, default="interactive", choices=["interactive", "daemon", "resume"], help="Run mode")
    parser.add_argument("--thread_id", type=str, help="Resume specific thread ID")
    
    args = parser.parse_args()
    run_agent(mode=args.mode, thread_id=args.thread_id)
