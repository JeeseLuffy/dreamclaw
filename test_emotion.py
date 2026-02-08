import unittest
from dclaw.emotion import EmotionState

class TestEmotionState(unittest.TestCase):
    def test_initialization(self):
        es = EmotionState()
        state = es.get_state()
        self.assertAlmostEqual(state["Curiosity"], 0.5, places=3)
        self.assertAlmostEqual(state["Fatigue"], 0.0, places=3)
        self.assertEqual(len(getattr(es, "pad", [])), 3)

    def test_normalization(self):
        # Test capping at 1.0 and floor at 0.0
        es = EmotionState({"Curiosity": 1.5, "Fatigue": -0.5})
        state = es.get_state()
        self.assertEqual(state["Curiosity"], 1.0)
        self.assertEqual(state["Fatigue"], 0.0)

    def test_update_browse_interesting(self):
        es = EmotionState()
        initial_pad = list(es.pad)
        es.update("browse_interesting")
        self.assertGreater(es.pad[0], initial_pad[0])  # Pleasure increases
        self.assertGreater(es.pad[1], initial_pad[1])  # Arousal increases

    def test_update_post_ignored(self):
        es = EmotionState()
        initial_pad = list(es.pad)
        es.update("post_ignored")
        self.assertLess(es.pad[0], initial_pad[0])  # Pleasure decreases

    def test_parameter_mapping(self):
        # Test high Pleasure + Arousal -> Enthusiastic Tone
        es = EmotionState({"Excitement": 0.8, "Joy": 0.8, "Curiosity": 0.5, "Fatigue": 0.0, "Anxiety": 0.0, "Frustration": 0.0})
        params = es.get_generation_params()
        self.assertEqual(params["tone"], "enthusiastic")
        
        # Test low Pleasure + high Dominance -> Frustrated Tone
        es = EmotionState({"Frustration": 1.0, "Curiosity": 0.0, "Fatigue": 0.0, "Joy": 0.0, "Anxiety": 0.0, "Excitement": 0.0})
        params = es.get_generation_params()
        self.assertEqual(params["tone"], "frustrated")

if __name__ == '__main__':
    unittest.main()
