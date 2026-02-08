from dclaw.graph import build_graph
import uuid

def test_workflow():
    print("Initializing Graph...")
    app = build_graph()
    
    # Initial State
    initial_state = {
        "messages": [],
        "emotion_vector": {
            "Curiosity": 0.5, "Fatigue": 0.0, "Joy": 0.5, 
            "Anxiety": 0.2, "Excitement": 0.3, "Frustration": 0.1
        },
        "daily_token_budget": 1000,
        "post_history": [],
        "memory_context": []
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
