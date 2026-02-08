import os
from mem0 import Memory
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

class MockMemory:
    """
    In-memory mock for Mem0 to facilitate testing without LLM/DB dependencies.
    """
    def __init__(self, config=None):
        self.data = []
        print("Initialized MockMemory")

    def add(self, messages, user_id, metadata=None):
        entry = {
            "messages": messages,
            "user_id": user_id,
            "metadata": metadata or {},
            "memory": messages[0]["content"] if messages else ""
        }
        self.data.append(entry)
        print(f"MockMemory Add: {entry['memory'][:50]}...")
        return {"id": len(self.data)}

    def search(self, query, user_id, limit=5):
        # Simple substring search mock
        results = [
            d for d in self.data 
            if d["user_id"] == user_id and (query.lower() in d["memory"].lower())
        ]
        return results[:limit]

    def get_all(self, user_id, filters=None):
        results = [d for d in self.data if d["user_id"] == user_id]
        if filters:
            for key, value in filters.items():
                results = [r for r in results if r["metadata"].get(key) == value]
        return results
    
    @classmethod
    def from_config(cls, config):
        return cls(config)

class AgentMemory:
    """
    Wrapper for Mem0 memory system managing long-term (graph/vector) and short-term memory.
    """
    def __init__(self, user_id: str = "dclaw_agent"):
        self.user_id = user_id
        
        # Configuration for Mem0
        # For this implementation, we will use a local vector store (Chroma) 
        # and a mock graph store configuration if Neo4j is not available,
        # or assume Neo4j is running locally.
        
        # NOTE: Switching to MockMemory for development/testing without API keys
        self.memory = MockMemory() 
        
        # Real Config (for reference/future enablement)
        # config = {
        #     "vector_store": {
        #         "provider": "qdrant",
        #         "config": {
        #             "path": "./qdrant_db",
        #         }
        #     },
        #     "embedder": {
        #         "provider": "huggingface",
        #         "config": {
        #             "model": "sentence-transformers/all-MiniLM-L6-v2"
        #         }
        #     }
        # }
        # try:
        #     self.memory = Memory.from_config(config)
        # except Exception as e:
        #     print(f"Failed to initialize real Mem0: {e}. Falling back to MockMemory.")
        #     self.memory = MockMemory()

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
        results = self.memory.get_all(user_id=self.user_id, filters={"type": "persona"})
        if results:
             return "\n".join([res["memory"] for res in results])
        return "You are a helpful AI assistant."

    def reflect_and_consolidate(self):
        """
        Reflects on short-term memories and consolidates them into insights.
        (Simplified implementation)
        """
        # 1. Retrieve recent short-term memories (Mock retrieval for now as filters might need tuning)
        # In a real scenario: recent = self.memory.get_all(user_id=self.user_id, filters={"type": "short_term"})
        
        # 2. Use LLM to summarize (Mocked here)
        insight = "User is interested in AI Agent development and memory systems."
        
        # 3. Store as 'insight' type
        self.memory.add(
            messages=[{"role": "system", "content": insight}],
            user_id=self.user_id,
            metadata={"type": "insight", "source": "reflection"}
        )
        print(f"Reflected and stored insight: {insight}")

    def initialize_persona(self, description: str):
        """
        Sets the initial persona if not present.
        """
        existing = self.memory.get_all(user_id=self.user_id, filters={"type": "persona"})
        if not existing:
             self.memory.add(
                messages=[{"role": "system", "content": description}],
                user_id=self.user_id,
                metadata={"type": "persona"}
            )
