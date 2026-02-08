from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import List
import sqlite3
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import ollama
from .state import AgentState
from .memory import AgentMemory
from .emotion import EmotionState
from .critic import ContentCritic, DailyConstraint
from .perception import PerceptionLayer
from .config import AgentConfig


class AgentRuntime:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.memory_system = AgentMemory(
            use_real_mem0=config.use_real_mem0,
            vector_store_provider=config.vector_store_provider,
        )
        self.perception_layer = PerceptionLayer()
        self.llm = None
        self.llm_invoke = None
        if config.use_llm_generation:
            provider = config.llm_provider.lower()
            if provider == "openai":
                try:
                    self.llm = ChatOpenAI(model=config.model_name)
                except Exception as exc:
                    print(f"LLM init failed ({exc}); using rule-only mode.")
                    self.llm = None
            elif provider == "ollama":
                self.llm_invoke = self._ollama_invoke
            else:
                print(f"Unsupported llm provider: {provider}. Using rule-only mode.")

        self.critic_system = ContentCritic(
            llm=self.llm,
            llm_invoke=self.llm_invoke,
            use_prompt_critic=config.use_prompt_critic,
        )
        self.daily_constraint = DailyConstraint(
            max_tokens=config.max_tokens_per_day,
            max_posts=config.max_posts_per_day,
        )

    def _ollama_invoke(self, prompt: str) -> str:
        try:
            response = ollama.generate(model=self.config.model_name, prompt=prompt)
            return response.get("response", "").strip()
        except Exception as exc:
            print(f"Ollama generation failed ({exc}); using empty response.")
            return ""

    def _generate_draft(self, persona: str, tone: str, temperature: float, context_str: str, idx: int) -> str:
        if self.llm is None and self.llm_invoke is None:
            return f"[{tone}] Insight {idx}: {context_str[:80]} #AI #dreamclaw"

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are DreamClaw, a social AI agent.\n"
                    "Persona: {persona}\n"
                    "Tone: {tone}\n"
                    "Creativity temperature hint: {temperature}\n"
                    "Generate one concise post under 280 characters.",
                ),
                ("user", "Context:\n{context}\n\nVariant seed: {seed}"),
            ]
        )
        payload = {
            "persona": persona,
            "tone": tone,
            "temperature": temperature,
            "context": context_str,
            "seed": idx,
        }
        try:
            if self.llm_invoke is not None:
                rendered_messages = prompt.format_messages(**payload)
                rendered_prompt = "\n\n".join(msg.content for msg in rendered_messages)
                text = self.llm_invoke(rendered_prompt)
                if text:
                    return text
            elif self.llm is not None:
                chain = prompt | self.llm | StrOutputParser()
                return chain.invoke(payload)
        except Exception as exc:
            print(f"Draft generation failed ({exc}); using fallback.")
        return f"[{tone}] Thought {idx}: {context_str[:80]} #AI #dreamclaw"

    def perception_node(self, state: AgentState):
        print("--- 1. Perception/Browsing ---")
        browsed_content = self.perception_layer.browse(platform="reddit", limit=3)
        if browsed_content:
            first_item = browsed_content[0]
            title = first_item.get("title", "Untitled")
            content = first_item.get("content", "")
            new_memory = f"{title}: {content}".strip()
        else:
            new_memory = "Nothing interesting found."

        self.memory_system.add_interaction(role="user", content=new_memory, metadata={"source": "reddit"})

        post_history = state.get("post_history", [])
        engagement = self.perception_layer.analyze_engagement(post_history)

        emotion_engine = EmotionState(state.get("emotion_vector"))
        event = "get_like" if engagement.get("likes", 0) > 20 else "browse_interesting"
        new_vector = emotion_engine.update(event)

        return {
            "messages": [f"Browsed: {new_memory}"],
            "emotion_vector": new_vector,
            "memory_context": [new_memory],
        }

    def draft_node(self, state: AgentState):
        print("--- 2. Drafting Content ---")
        emotion_engine = EmotionState(state["emotion_vector"])
        params = emotion_engine.get_generation_params()

        memory_context = self.memory_system.search_memory("AI agents social media", limit=self.config.memory_top_k)
        context_str = "\n".join(memory_context) if memory_context else "general AI trends"
        persona = self.memory_system.get_persona()

        candidates: List[str] = []
        for idx in range(self.config.candidate_drafts):
            candidates.append(
                self._generate_draft(
                    persona=persona,
                    tone=params["tone"],
                    temperature=params["temperature"],
                    context_str=context_str,
                    idx=idx + 1,
                )
            )

        return {
            "draft_candidates": candidates,
            "draft_content": candidates[0] if candidates else None,
            "memory_context": memory_context,
            "messages": [f"Generated {len(candidates)} candidate drafts."],
        }

    def critic_node(self, state: AgentState):
        print("--- 3. Critic Review ---")
        candidates = state.get("draft_candidates", [])
        if not candidates and state.get("draft_content"):
            candidates = [state["draft_content"]]

        persona = self.memory_system.get_persona()
        tone = EmotionState(state["emotion_vector"]).get_generation_params()["tone"]
        memory_context = state.get("memory_context", [])

        best_result = None
        best_draft = None
        for draft in candidates:
            result = self.critic_system.evaluate(
                content=draft,
                persona=persona,
                tone=tone,
                memory_context=memory_context,
            )
            if best_result is None or result["final_score"] > best_result["final_score"]:
                best_result = result
                best_draft = draft

        if best_result is None:
            best_result = {"final_score": 0.0, "feedback": "No draft available."}
            best_draft = None

        can_post = self.daily_constraint.can_post(content=best_draft or "", estimated_tokens=0)
        budget_flag = 1 if can_post else 0

        return {
            "draft_content": best_draft,
            "quality_score": float(best_result["final_score"]),
            "critic_feedback": str(best_result["feedback"]),
            "daily_token_budget": budget_flag,
            "messages": [f"Best draft score: {best_result['final_score']}"],
        }

    def decision_node(self, state: AgentState):
        print("--- 4. Decision ---")
        score = state.get("quality_score", 0.0)
        budget = state.get("daily_token_budget", 0)
        if score >= self.config.quality_threshold and budget > 0:
            return "post"
        print("Draft rejected or budget exceeded.")
        return "reject"

    def post_node(self, state: AgentState):
        print("--- 5. Posting ---")
        draft = state.get("draft_content") or ""
        labeled_post = f"{self.config.agent_label} {draft}".strip()

        self.daily_constraint.record_post(content=labeled_post)
        print(f"POSTED TO SOCIAL MEDIA: {labeled_post}")

        self.memory_system.add_interaction(
            role="assistant",
            content=labeled_post,
            metadata={"type": "post", "status": "published"},
        )
        insights = self.memory_system.reflect_and_consolidate()

        return {
            "post_history": [{"content": labeled_post, "status": "published"}],
            "draft_content": None,
            "draft_candidates": [],
            "messages": [f"Posted with label. Reflection insights: {len(insights)}"],
        }


def build_graph(config: AgentConfig | None = None):
    """
    Constructs the compiled LangGraph application.
    """
    config = config or AgentConfig.from_env()
    runtime = AgentRuntime(config)

    conn = sqlite3.connect(config.checkpointer_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    workflow = StateGraph(AgentState)

    workflow.add_node("perceive", runtime.perception_node)
    workflow.add_node("draft", runtime.draft_node)
    workflow.add_node("critic", runtime.critic_node)
    workflow.add_node("post", runtime.post_node)

    workflow.set_entry_point("perceive")
    workflow.add_edge("perceive", "draft")
    workflow.add_edge("draft", "critic")
    workflow.add_conditional_edges(
        "critic",
        runtime.decision_node,
        {"post": "post", "reject": "perceive"},
    )
    workflow.add_edge("post", END)
    return workflow.compile(checkpointer=checkpointer)
