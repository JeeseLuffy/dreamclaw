import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import re

try:
    from mem0 import Memory
except Exception:
    Memory = None


class InMemoryStore:
    def __init__(self):
        self.records: List[Dict[str, Any]] = []

    def add(self, messages: List[Dict[str, str]], user_id: str, metadata: Dict[str, Any]):
        content = messages[0]["content"] if messages else ""
        self.records.append(
            {
                "user_id": user_id,
                "memory": content,
                "metadata": metadata.copy(),
                "created_at": datetime.now().isoformat(),
            }
        )

    def search(self, query: str, user_id: str, limit: int = 5):
        tokens = {token for token in re.findall(r"[a-zA-Z]{3,}", query.lower())}
        scored = []
        for record in self.records:
            if record["user_id"] != user_id:
                continue
            text = record["memory"].lower()
            overlap = sum(1 for token in tokens if token in text)
            scored.append((overlap, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def get_all(self, user_id: str, filters: Optional[Dict[str, Any]] = None):
        filters = filters or {}
        output = []
        for record in self.records:
            if record["user_id"] != user_id:
                continue
            matched = True
            for key, value in filters.items():
                if record.get("metadata", {}).get(key) != value:
                    matched = False
                    break
            if matched:
                output.append(record)
        return output

    def delete(self, user_id: str, filters: Optional[Dict[str, Any]] = None):
        filters = filters or {}
        kept = []
        for record in self.records:
            if record["user_id"] != user_id:
                kept.append(record)
                continue
            matched = True
            for key, value in filters.items():
                if record.get("metadata", {}).get(key) != value:
                    matched = False
                    break
            if not matched:
                kept.append(record)
        self.records = kept

class AgentMemory:
    """
    Wrapper for Mem0 memory system managing long-term (graph/vector) and short-term memory.
    """
    def __init__(
        self,
        user_id: str = "dclaw_agent",
        use_real_mem0: bool = False,
        vector_store_provider: str = "qdrant",
    ):
        self.user_id = user_id
        self.using_mock = True
        self.memory = InMemoryStore()

        should_try_real = (
            use_real_mem0
            and Memory is not None
            and bool(os.getenv("OPENAI_API_KEY"))
        )
        if not should_try_real:
            print("Using in-memory fallback store.")
            return

        config = {
            "vector_store": {
                "provider": vector_store_provider,
                "config": {"path": "./qdrant_db"},
            },
            "embedder": {
                "provider": "openai",
                "config": {"model": "text-embedding-3-small"},
            },
            "llm": {
                "provider": "openai",
                "config": {"model": "gpt-4o-mini"},
            },
        }

        try:
            self.memory = Memory.from_config(config)
            self.using_mock = False
            print("Mem0 initialized with vector memory.")
        except Exception as exc:
            print(f"Mem0 init failed ({exc}); using in-memory fallback.")
            self.memory = InMemoryStore()
            self.using_mock = True

    def add_interaction(self, role: str, content: str, metadata: Optional[Dict] = None):
        """
        Adds a short-term interaction to memory.
        """
        if metadata is None:
            metadata = {}
        
        metadata["timestamp"] = datetime.now().isoformat()
        metadata["type"] = metadata.get("type", "short_term")
        
        self.memory.add(
            messages=[{"role": role, "content": content}],
            user_id=self.user_id,
            metadata=metadata
        )

    def search_memory(self, query: str, limit: int = 5) -> List[str]:
        """
        Retrieves relevant memories for a given query.
        """
        try:
            results = self.memory.search(query=query, user_id=self.user_id, limit=limit)
            return [res.get("memory", "") for res in results if res.get("memory")]
        except Exception:
            return []

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
                return "\n".join([res.get("memory", "") for res in results if res.get("memory")])
        except Exception:
            pass
        return "You are a helpful AI assistant."

    def reflect_and_consolidate(self, lookback_hours: int = 24) -> List[str]:
        """
        Reflects on short-term memories and consolidates them into simple insights.
        """
        insights: List[str] = []
        since = datetime.now() - timedelta(hours=lookback_hours)

        try:
            recent = self.memory.get_all(user_id=self.user_id)
        except Exception:
            recent = []

        short_memories = []
        for item in recent:
            metadata = item.get("metadata", {})
            if metadata.get("type") != "short_term":
                continue
            timestamp = metadata.get("timestamp")
            if timestamp:
                try:
                    ts = datetime.fromisoformat(timestamp)
                    if ts < since:
                        continue
                except Exception:
                    pass
            short_memories.append(item.get("memory", ""))

        if not short_memories:
            return insights

        combined = " ".join(short_memories).lower()
        focus = "AI systems"
        if "agent" in combined:
            focus = "agent design"
        elif "memory" in combined:
            focus = "memory architecture"
        elif "open source" in combined:
            focus = "open-source tooling"

        insights.append(f"I am currently focused on {focus}.")
        insights.append("I prefer sharing concise, actionable technical updates.")

        for insight in insights:
            self.add_interaction(
                role="system",
                content=insight,
                metadata={"type": "insight", "source": "reflection"},
            )
        return insights

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
