from datetime import datetime, timedelta
import random

class ContentCritic:
    """
    Evaluates content quality using a (Mocked) BERT model.
    """
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        if not use_mock:
            # Placeholder for actual BERT model initialization
            # from transformers import pipeline
            # self.classifier = pipeline("text-classification", model="bert-base-uncased")
            pass

    def score(self, content: str) -> float:
        """
        Scores the content from 0.0 to 1.0.
        """
        if self.use_mock:
            # Mock scoring based on length and keywords availability
            score = 0.5
            if len(content) > 20: score += 0.2
            if "#AI" in content: score += 0.1
            if "dclaw" in content: score += 0.1
            return min(1.0, score)
        else:
            # Real implementation would go here
            return 0.8

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

    def can_post(self, estimated_tokens: int = 50) -> bool:
        self._check_reset()
        if self.posts_today >= self.max_posts:
            return False
        if self.tokens_used_today + estimated_tokens > self.max_tokens:
            return False
        return True

    def record_post(self, tokens: int = 50):
        self._check_reset()
        self.posts_today += 1
        self.tokens_used_today += tokens
