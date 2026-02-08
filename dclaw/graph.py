from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict, Annotated, List
import sqlite3
import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from .state import AgentState
from .memory import AgentMemory
from .emotion import EmotionState
from .critic import ContentCritic, DailyConstraint
from .perception import PerceptionLayer

# Initialize Systems
memory_system = AgentMemory()
critic_system = ContentCritic()
daily_constraint = DailyConstraint(max_posts=5) # increased for testing
perception_layer = PerceptionLayer()
llm = ChatOpenAI(model="gpt-4o-mini")

def perception_node(state: AgentState):
    """
    Simulates browsing social media and updating state.
    """
    print("--- 1. Perception/Browsing ---")
    
    # Browse Content
    browsed_content = perception_layer.browse(platform="reddit", limit=3)
    new_memory = browsed_content[0]["title"] + ": " + browsed_content[0]["content"] if browsed_content else "Nothing interesting found."
    
    print(f"Browsed: {new_memory[:50]}...")
    
    # Store in memory
    memory_system.add_interaction(role="user", content=new_memory, metadata={"source": "reddit"})
    
    # Analyze Engagement on previous posts (if any)
    post_history = state.get("post_history", [])
    engagement = perception_layer.analyze_engagement(post_history)
    
    # Emotion Update
    current_vector = state.get("emotion_vector")
    emotion_engine = EmotionState(current_vector)
    
    # Simulate an event based on browsing/engagement
    if engagement.get("likes", 0) > 20:
        new_vector = emotion_engine.update("get_like")
    else:
        new_vector = emotion_engine.update("browse_interesting")
    
    return {
        "messages": [f"Browsed: {new_memory}"],
        "emotion_vector": new_vector,
        "memory_context": [new_memory]
    }

def draft_node(state: AgentState):
    """
    Generates a draft post based on current state and emotions.
    """
    print("--- 2. Drafting Content ---")
    
    # Emotion Parameters
    emotion_engine = EmotionState(state["emotion_vector"])
    params = emotion_engine.get_generation_params()
    print(f"Generation Params: {params}")
    
    # Retrieve relevant context from memory
    query = "AI agents social media"
    memory_context = memory_system.search_memory(query)
    context_str = "\n".join(memory_context) if memory_context else "general AI trends"
    
    # LLM Generation
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are DClaw, a social AI agent. Your persona is: {persona}. \n"
                   "Current state of mind: {tone}. Creativity level (temperature): {temperature}. \n"
                   "Draft a short social media post (under 280 chars) based on the context below."),
        ("user", "Context: {context}")
    ])
    
    persona = memory_system.get_persona()
    chain = prompt | llm
    
    try:
        response = chain.invoke({
            "persona": persona,
            "tone": params["tone"],
            "temperature": params["temperature"],
            "context": context_str
        })
        draft = response.content
    except Exception as e:
        print(f"LLM generation failed: {e}. Using fallback.")
        draft = f"Just read about {context_str[:20]}... I'm feeling {params['tone']}! #AI #dclaw"
    
    print(f"Generated Draft: {draft}")
    
    return {"draft_content": draft, "memory_context": memory_context}

def critic_node(state: AgentState):
    """
    Evaluates the draft for quality and policy compliance.
    """
    print("--- 3. Critic Review ---")
    draft = state.get("draft_content", "")
    
    # Score content
    score = critic_system.score(draft)
    print(f"Critic Score: {score}")
    
    # Check budget
    can_post = daily_constraint.can_post()
    if not can_post:
        print("Daily post limit reached.")
    
    return {
        "quality_score": score,
        "daily_token_budget": 1 if can_post else 0 # Simple flag for decision node
    }

def decision_node(state: AgentState):
    """
    Decides whether to post or retry based on critic score.
    """
    print("--- 4. Decision ---")
    score = state.get("quality_score", 0.0)
    budget = state.get("daily_token_budget", 0)
    
    if score > 0.6 and budget > 0: # Threshold 0.6
        return "post"
    else:
        print("Draft rejected or budget exceeded.")
        return "reject"

def post_node(state: AgentState):
    """
    Publishes the content and updates history.
    """
    print("--- 5. Posting ---")
    draft = state["draft_content"]
    
    # Update quota
    daily_constraint.record_post()
    
    # Mock posting
    print(f"POSTED TO SOCIAL MEDIA: {draft}")
    
    # Store post in memory
    memory_system.add_interaction(role="assistant", content=draft, metadata={"type": "post", "status": "published"})
    
    # Trigger reflection
    memory_system.reflect_and_consolidate()
    
    return {
        "post_history": [{"content": draft, "status": "published"}],
        "draft_content": None # Clear draft
    }

def build_graph():
    """
    Constructs the compiled LangGraph application.
    """
    # Initialize SQLite checkpointer
    db_path = "agent_state.db"
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    # Define Graph
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("perceive", perception_node)
    workflow.add_node("draft", draft_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("post", post_node)

    # Set Entry Point
    workflow.set_entry_point("perceive")

    # Add Edges
    workflow.add_edge("perceive", "draft")
    workflow.add_edge("draft", "critic")
    
    # Conditional Edges
    workflow.add_conditional_edges(
        "critic",
        decision_node,
        {
            "post": "post",
            "reject": "perceive" # Loop back to browse more if content is bad
        }
    )
    
    workflow.add_edge("post", END)

    # Compile
    app = workflow.compile(checkpointer=checkpointer)
    return app
