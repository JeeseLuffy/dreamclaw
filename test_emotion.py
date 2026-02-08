import unittest
from dclaw.emotion import EmotionState

class TestEmotionState(unittest.TestCase):
    def test_initialization(self):
        es = EmotionState()
        self.assertEqual(es.vector["Curiosity"], 0.5)
        self.assertEqual(es.vector["Fatigue"], 0.0)

    def test_normalization(self):
        # Test capping at 1.0 and floor at 0.0
        es = EmotionState({"Curiosity": 1.5, "Fatigue": -0.5})
        self.assertEqual(es.vector["Curiosity"], 1.0)
        self.assertEqual(es.vector["Fatigue"], 0.0)

    def test_update_browse_interesting(self):
        es = EmotionState()
        initial_curiosity = es.vector["Curiosity"]
        es.update("browse_interesting")
        self.assertGreater(es.vector["Curiosity"], initial_curiosity)

    def test_update_post_ignored(self):
        es = EmotionState()
        initial_frustration = es.vector["Frustration"]
        es.update("post_ignored")
        self.assertGreater(es.vector["Frustration"], initial_frustration)

    def test_parameter_mapping(self):
        # Test High Excitement -> Enthusiastic Tone
        es = EmotionState({"Excitement": 0.8, "Joy": 0.8, "Curiosity": 0.5, "Fatigue": 0.0, "Anxiety": 0.0, "Frustration": 0.0})
        params = es.get_generation_params()
        self.assertEqual(params["tone"], "enthusiastic")
        
        # Test High Frustration -> Critical Tone
        es = EmotionState({"Frustration": 0.9, "Curiosity": 0.5, "Fatigue": 0.0, "Joy": 0.0, "Anxiety": 0.0, "Excitement": 0.0})
        params = es.get_generation_params()
        self.assertEqual(params["tone"], "critical")

if __name__ == '__main__':
    unittest.main()
