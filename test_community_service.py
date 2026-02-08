import tempfile
import unittest
from pathlib import Path

from dclaw.community_config import CommunityConfig
from dclaw.community_service import CommunityService


class TestCommunityService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(self.temp_dir.name) / "community_test.db")
        config = CommunityConfig(
            db_path=db_path,
            provider="openai",
            model="gpt-4o-mini",
            ai_population=3,
            scheduler_interval_seconds=10,
        )
        self.service = CommunityService(config)
        self.service.random.seed(1234)

    def tearDown(self):
        self.service.db.close()
        self.temp_dir.cleanup()

    def test_register_creates_permanent_ai_binding(self):
        user = self.service.register_or_login("alice_01")
        user_again = self.service.register_or_login("alice_01")
        self.assertEqual(user["user_id"], user_again["user_id"])
        self.assertEqual(user["ai_account_id"], user_again["ai_account_id"])
        self.assertIn("provider", user)
        self.assertIn("model", user)

    def test_human_daily_limit(self):
        user = self.service.register_or_login("bob_01")
        for index in range(10):
            created = self.service.create_human_content(user["user_id"], f"post {index}")
            self.assertIsNotNone(created["id"])
        with self.assertRaises(ValueError):
            self.service.create_human_content(user["user_id"], "post overflow")

    def test_ai_limits(self):
        user = self.service.register_or_login("carol_01")
        ai_id = user["ai_account_id"]

        allowed_post, _ = self.service._check_publish_permission("ai", ai_id, "post")
        self.assertTrue(allowed_post)
        self.service._consume_quota("ai", ai_id, "post")
        allowed_post_after, _ = self.service._check_publish_permission("ai", ai_id, "post")
        self.assertFalse(allowed_post_after)

        allowed_comment_1, _ = self.service._check_publish_permission("ai", ai_id, "comment")
        self.assertTrue(allowed_comment_1)
        self.service._consume_quota("ai", ai_id, "comment")
        allowed_comment_2, _ = self.service._check_publish_permission("ai", ai_id, "comment")
        self.assertTrue(allowed_comment_2)
        self.service._consume_quota("ai", ai_id, "comment")
        allowed_comment_3, _ = self.service._check_publish_permission("ai", ai_id, "comment")
        self.assertFalse(allowed_comment_3)

    def test_ai_tick_creates_trace(self):
        stats = self.service.run_ai_tick(max_agents=1)
        self.assertEqual(stats["processed"], 1)
        traces = self.service.recent_traces(limit=5)
        self.assertGreaterEqual(len(traces), 1)

    def test_model_update_with_whitelist(self):
        user = self.service.register_or_login("diana_01")
        updated = self.service.update_user_ai_model(user["user_id"], "ollama", "llama3:latest")
        self.assertEqual(updated["provider"], "ollama")
        self.assertEqual(updated["model"], "llama3:latest")
        with self.assertRaises(ValueError):
            self.service.update_user_ai_model(user["user_id"], "ollama", "not-exists-model")

    def test_metrics_shape(self):
        metrics = self.service.community_metrics()
        for key in [
            "users",
            "ai_accounts",
            "posts",
            "comments",
            "likes",
            "emotion_continuity",
            "persona_consistency",
            "interaction_quality",
            "avg_quality",
        ]:
            self.assertIn(key, metrics)


if __name__ == "__main__":
    unittest.main()
