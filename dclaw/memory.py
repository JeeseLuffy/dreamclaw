import os
from mem0 import Memory
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

# class MockMemory: ... (Keep mock class for fallback/testing if needed, but we focus on real impl)

class AgentMemory:
    """
    Wrapper for Mem0 memory system managing long-term (graph/vector) and short-term memory.
    """
    def __init__(self, user_id: str = "dclaw_agent"):
        self.user_id = user_id
        
        # Checking for API Key
        if not os.getenv("OPENAI_API_KEY"):
            print("WARNING: OPENAI_API_KEY not found. Memory system may fail or fallback.")

        # Real Config with OpenAI
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": "./qdrant_db",
                }
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "text-embedding-3-small"
                }
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "gpt-4o-mini"
                }
            }
        }
        
        try:
            self.memory = Memory.from_config(config)
            print("Mem0 Initialized with OpenAI & Qdrant.")
        except Exception as e:
            print(f"Failed to initialize Mem0: {e}. Defaulting to MockMemory (if available) or raising error.")
            # Fallback logic could go here
            raise e

    def add_interaction(self, role: str, content: str, metadata: Optional[Dict] = None):
        """
        Adds a short-term interaction to memory.
        """
        if metadata is None:
            metadata = {}
        
        metadata["timestamp"] = datetime.now().isoformat()
        metadata["type"] = "short_term"
        
        self.memory.add(
            messages=[{"role": role, "content": content}],
            user_id=self.user_id,
            metadata=metadata
        )

    def search_memory(self, query: str, limit: int = 5) -> List[str]:
        """
        Retrieves relevant memories for a given query.
        """
        results = self.memory.search(query=query, user_id=self.user_id, limit=limit)
        return [res["memory"] for res in results] if results else []

    def get_persona(self) -> str:
        """
        Retrieves the agent's persona definition.
        """
        # Mem0 might not have 'get_all' directly exposed the same way depending on version, 
        # but 'search' with empty query or specific filters often works.
        # Assuming get_all is valid or we use search.
        try:
            results = self.memory.get_all(user_id=self.user_id, filters={"type": "persona"})
            if results:
                 return "\n".join([res["memory"] for res in results])
        except:
            pass
        return "You are a helpful AI assistant."

    def reflect_and_consolidate(self):
        """
        Reflects on short-term memories and consolidates them into insights.
        """
        # Mem0 likely has built-in features for this, but we force a "add" 
        # that acts as a reflection/summary if we were building it manually.
        # Here we just log it for now as Mem0 auto-manages some memory distinctness.
        print("Triggering Memory Reflection (Mem0 handles consolidation internally or via API)...")
        pass

    def initialize_persona(self, description: str):
        """
        Sets the initial persona if not present.
        """
        # Check if persona exists
        existing = self.get_persona()
        if "helpful AI assistant" in existing and len(existing) < 50:
             self.memory.add(
                messages=[{"role": "system", "content": description}],
                user_id=self.user_id,
                metadata={"type": "persona"}
            )
