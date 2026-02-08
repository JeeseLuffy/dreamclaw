import unittest

from dclaw.critic import ContentCritic, DailyConstraint
from dclaw.memory import AgentMemory


class TestCriticAndMemory(unittest.TestCase):
    def test_hybrid_critic_rule_mode(self):
        critic = ContentCritic(llm=None, use_prompt_critic=False)
        result = critic.evaluate(
            content="New open-source agent workflow with memory reflection. #AI #dclaw",
            persona="You are a technical AI agent.",
            tone="objective",
            memory_context=["agent workflow", "memory reflection"],
        )
        self.assertGreaterEqual(result["final_score"], 0.0)
        self.assertLessEqual(result["final_score"], 1.0)
        self.assertEqual(result["prompt_score"], -1.0)

    def test_daily_constraint_one_post_limit(self):
        constraint = DailyConstraint(max_tokens=1000, max_posts=1)
        self.assertTrue(constraint.can_post(content="hello world"))
        constraint.record_post(content="hello world")
        self.assertFalse(constraint.can_post(content="second post"))

    def test_memory_reflection_with_fallback_store(self):
        memory = AgentMemory(use_real_mem0=False)
        memory.add_interaction("user", "I read about agent memory architecture today.")
        memory.add_interaction("user", "I like concise technical posts.")
        insights = memory.reflect_and_consolidate(lookback_hours=48)
        self.assertGreaterEqual(len(insights), 1)


if __name__ == "__main__":
    unittest.main()
