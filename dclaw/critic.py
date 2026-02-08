from datetime import datetime
from typing import Dict, List, Optional
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

class ContentCritic:
    """
    Hybrid critic: rule-based score + optional prompt-based score.
    """
    def __init__(self, llm=None, use_prompt_critic: bool = True):
        self.llm = llm
        self.use_prompt_critic = use_prompt_critic and llm is not None

    def _rule_score(self, content: str, memory_context: Optional[List[str]] = None) -> float:
        score = 0.35
        content_len = len(content.strip())
        if 40 <= content_len <= 280:
            score += 0.2
        elif content_len > 20:
            score += 0.1

        if "#AI" in content or "#dclaw" in content.lower():
            score += 0.1

        if "http" in content:
            score += 0.05

        if content.count("!") <= 2:
            score += 0.05

        if memory_context:
            overlap = self._memory_overlap(content, memory_context)
            score += min(0.25, overlap * 0.25)

        return max(0.0, min(1.0, round(score, 3)))

    def _memory_overlap(self, content: str, memory_context: List[str]) -> float:
        source = " ".join(memory_context).lower()
        content_words = {
            word
            for word in re.findall(r"[a-zA-Z]{4,}", content.lower())
            if word not in {"this", "that", "with", "have", "from"}
        }
        if not content_words:
            return 0.0
        overlap = sum(1 for word in content_words if word in source)
        return overlap / len(content_words)

    def _prompt_score(self, content: str, persona: str, tone: str) -> Dict[str, str]:
        if not self.use_prompt_critic:
            return {"score": None, "feedback": "Prompt critic disabled."}

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a strict social-media editor. Rate draft quality from 0 to 1.\n"
                    "Return exactly: SCORE=<number>;FEEDBACK=<short reason>.",
                ),
                (
                    "user",
                    "Persona:\n{persona}\n\nDesired tone: {tone}\n\nDraft:\n{draft}",
                ),
            ]
        )

        try:
            chain = prompt | self.llm | StrOutputParser()
            raw = chain.invoke({"persona": persona, "tone": tone, "draft": content})
            score_match = re.search(r"SCORE\s*=\s*([0-1](?:\.\d+)?)", raw)
            feedback_match = re.search(r"FEEDBACK\s*=\s*(.+)", raw)
            score = float(score_match.group(1)) if score_match else None
            feedback = feedback_match.group(1).strip() if feedback_match else raw.strip()
            if score is not None:
                score = max(0.0, min(1.0, score))
            return {"score": score, "feedback": feedback}
        except Exception as exc:
            return {"score": None, "feedback": f"Prompt critic failed: {exc}"}

    def evaluate(
        self,
        content: str,
        persona: str,
        tone: str = "objective",
        memory_context: Optional[List[str]] = None,
    ) -> Dict[str, float | str]:
        rule_score = self._rule_score(content, memory_context)
        prompt_eval = self._prompt_score(content, persona, tone)
        prompt_score = prompt_eval["score"]
        feedback = prompt_eval["feedback"]

        if prompt_score is None:
            final_score = rule_score
        else:
            final_score = round((0.6 * rule_score) + (0.4 * float(prompt_score)), 3)

        return {
            "final_score": final_score,
            "rule_score": rule_score,
            "prompt_score": prompt_score if prompt_score is not None else -1.0,
            "feedback": feedback,
        }

class DailyConstraint:
    """
    Manages daily token/post limits.
    """
    def __init__(self, max_tokens: int = 1000, max_posts: int = 1):
        self.max_tokens = max_tokens
        self.max_posts = max_posts
        self.posts_today = 0
        self.tokens_used_today = 0
        self.last_reset = datetime.now().date()

    def _check_reset(self):
        today = datetime.now().date()
        if today > self.last_reset:
            self.posts_today = 0
            self.tokens_used_today = 0
            self.last_reset = today

    def estimate_tokens(self, content: str) -> int:
        return max(1, int(len(content.split()) * 1.4))

    def can_post(self, content: str = "", estimated_tokens: int = 0) -> bool:
        self._check_reset()
        if estimated_tokens <= 0:
            estimated_tokens = self.estimate_tokens(content)
        if self.posts_today >= self.max_posts:
            return False
        if self.tokens_used_today + estimated_tokens > self.max_tokens:
            return False
        return True

    def record_post(self, content: str = "", tokens: int = 0):
        self._check_reset()
        if tokens <= 0:
            tokens = self.estimate_tokens(content)
        self.posts_today += 1
        self.tokens_used_today += tokens
