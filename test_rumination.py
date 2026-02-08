import unittest
from dclaw.rumination import RuminationEngine
from dclaw.memory import AgentMemory, InMemoryStore
from dclaw.emotion import EmotionState

class TestRuminationEngine(unittest.TestCase):
    def setUp(self):
        self.memory = AgentMemory(use_real_mem0=False)
        self.emotion_engine = EmotionState()
        self.engine = RuminationEngine(self.memory, self.emotion_engine)

    def test_rumination_cycle_no_memories(self):
        result = self.engine.run_rumination_cycle([])
        self.assertEqual(result["status"], "no_memories")

    def test_rumination_cycle_success(self):
        memories = ["I had a great interaction with a user about AI ethics."]
        # Initial baseline is 0,0,0 derived from init
        initial_pad = list(self.engine.emotion_engine.pad)
        
        # Mock LLM to return positive insight
        self.engine.llm_invoke = lambda x: "I feel very positive about the future."
        
        result = self.engine.run_rumination_cycle(memories)
        
        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(result["insight"])
        
        # Check if baseline shifted positively (P should increase)
        new_pad = result["new_pad_baseline"]
        # Sentiment 'positive' adds [0.2, 0.1, 0.1] * 0.1 = [0.02, 0.01, 0.01]
        self.assertGreater(new_pad[0], initial_pad[0])

    def test_sentiment_impact_negative(self):
        # Test internal sentiment logic
        delta = self.engine._analyze_sentiment_impact("This makes me sad and negative.")
        self.assertEqual(delta, [-0.2, -0.1, -0.1])

if __name__ == '__main__':
    unittest.main()
