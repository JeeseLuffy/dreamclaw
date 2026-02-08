import uuid
import time
import argparse
from dclaw.graph import build_graph, AgentRuntime
from dclaw.config import AgentConfig
from dclaw.rumination import RuminationEngine
from dclaw.emotion import EmotionState

def run_agent(mode="interactive", thread_id=None):
    if mode == "community-dashboard":
        from dclaw.community_dashboard import launch_dashboard
        port = int(getattr(run_agent, "_dashboard_port", 8501))
        launch_dashboard(port=port)
        return
    if mode == "community":
        from dclaw.community_tui import run as run_community_tui
        run_community_tui()
        return
    if mode == "community-online":
        from dclaw.community_online import run_api
        run_api()
        return
    if mode == "community-daemon":
        from dclaw.community_config import CommunityConfig
        from dclaw.community_daemon import daemon_status, run_daemon_loop, start_daemon, stop_daemon
        config = CommunityConfig.from_env()
        action = getattr(run_agent, "_daemon_action", "status")
        if action == "start":
            print(start_daemon(config))
        elif action == "stop":
            print(stop_daemon())
        elif action == "status":
            print(daemon_status())
        elif action == "run":
            run_daemon_loop(config)
        else:
            print(f"Unknown daemon action: {action}")
        return

    print(f"Starting DreamClaw Agent in {mode} mode...")
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
        "last_rumination_time": time.time(),
        "insight_history": [],
        "baseline_pad": [0.0, 0.0, 0.0]
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
            # Initialize Rumination Engine
            # We need access to runtime memory/emotion from the app context, 
            # but LangGraph hides runtime. simpler to instantiate a dedicated engine here 
            # sharing the same DB if possible, or just mock for now since Runtime isn't easily accessible from 'app'.
            # A better design would be to expose runtime from build_graph or use a global singleton.
            # For this MVP, we will re-instantiate a runtime helper or just pass the state's memory if we could.
            # Actually, let's just make a standalone engine that we MANUALLY feed state to/from.
            
            # Re-create runtime components for access (Not ideal but works for MVP without refactoring graph.py)
            runtime = AgentRuntime(config_obj) 
            rumination_engine = RuminationEngine(runtime.memory_system, EmotionState())

            state = initial_state # Keep track of local state for rumination
            
            while True:
                print(f"\n[{time.strftime('%X')}] Waking up agent...")
                
                # 1. Run standard Graph Cycle
                events_occurred = False
                for event in app.stream(state if inputs else None, config=config):
                    events_occurred = True
                    for node, values in event.items():
                        print(f"Processed Node: {node}")
                        # Update local state tracking
                        if isinstance(values, dict):
                            state.update(values)
                
                # 2. Check for Rumination Opportunity (Idle time)
                # If we just finished a cycle, we might want to sleep. 
                # If we have been idle for X seconds, trigger rumination.
                # For demo: force rumination if no major external events or just every loop
                
                last_rum = state.get("last_rumination_time", 0)
                if time.time() - last_rum > 30: # Mock 30s idle time
                     print("--- [Rumination] User idle. Entering internal thought... ---")
                     # Sync engine with current state
                     rumination_engine.emotion_engine.discrete_vector = state.get("emotion_vector", {})
                     rumination_engine.emotion_engine.pad = state.get("baseline_pad", [0,0,0]) # or current calculated PAD
                     
                     # Get recent memories (mock or from state)
                     recent_mems = state.get("memory_context", []) or ["Nothing special happened."]
                     
                     result = rumination_engine.run_rumination_cycle(recent_mems)
                     
                     if result["status"] == "success":
                         print(f"--- [Rumination] Insight: {result['insight']}")
                         print(f"--- [Rumination] New Baseline PAD: {result['new_pad_baseline']}")
                         
                         # Update State
                         state["last_rumination_time"] = time.time()
                         state["baseline_pad"] = result["new_pad_baseline"]
                         # In a real app we'd save this back to checkpointer
                
                print(f"[{time.strftime('%X')}] Sleeping for 10 seconds...")
                time.sleep(10)
                inputs = None 
                
        else:
             for event in app.stream(initial_state, config=config):
                for node, values in event.items():
                    print(f"Processed Node: {node}")
                    
    except KeyboardInterrupt:
        print("\nStopping Agent...")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DreamClaw Agent")
    parser.add_argument("--mode", type=str, default="interactive", choices=["interactive", "daemon", "resume", "community", "community-daemon", "community-online", "community-dashboard"], help="Run mode")
    parser.add_argument("--daemon-action", type=str, default="status", choices=["start", "stop", "status", "run"], help="Community daemon action")
    parser.add_argument("--dashboard-port", type=int, default=8501, help="Community dashboard port")
    parser.add_argument("--thread_id", type=str, help="Resume specific thread ID")
    
    args = parser.parse_args()
    setattr(run_agent, "_daemon_action", args.daemon_action)
    setattr(run_agent, "_dashboard_port", args.dashboard_port)
    run_agent(mode=args.mode, thread_id=args.thread_id)
