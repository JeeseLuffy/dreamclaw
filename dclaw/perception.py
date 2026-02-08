import random
from typing import List, Dict, Any

class PerceptionLayer:
    """
    Handles content ingestion from external sources (Reddit, X, etc.)
    Mocking BrowserUse for initial implementation.
    """
    def __init__(self):
        # In a real implementation, we would initialize BrowserUse here
        pass

    def browse(self, platform: str = "reddit", limit: int = 5) -> List[Dict[str, Any]]:
        """
        Browses the specified platform for interesting content.
        """
        print(f"Browsing {platform}...")
        
        # Mock Data
        reddit_posts = [
            {"title": "The future of Generative Agents", "content": "I think memory is key...", "upvotes": 120, "url": "reddit.com/r/AI/1"},
            {"title": "LangGraph vs LangChain", "content": "Cyclic graphs are game changers.", "upvotes": 85, "url": "reddit.com/r/LangChain/2"},
            {"title": "New model release: Llama-4", "content": "It's huge!", "upvotes": 500, "url": "reddit.com/r/LocalLLaMA/3"}, 
            {"title": "Why AI needs emotions", "content": "Pure logic isn't enough.", "upvotes": 200, "url": "reddit.com/r/Philosophy/4"}
        ]
        
        x_posts = [
            {"content": "Just built a new agent! #AI #buildinpublic", "likes": 50, "url": "x.com/user1/1"},
            {"content": "Is AGI coming in 2026? #AGI", "likes": 1000, "url": "x.com/user2/2"}
        ]
        
        source = reddit_posts if platform == "reddit" else x_posts
        
        # Randomly select a few
        selected = random.sample(source, min(limit, len(source)))
        return selected

    def analyze_engagement(self, post_history: List[Dict]) -> Dict[str, Any]:
        """
        Analyzes engagement on previous posts to feedback into the system.
        """
        # Mock feedback
        if not post_history:
            return {}
            
        last_post = post_history[-1]
        return {
            "likes": random.randint(0, 50),
            "replies": random.randint(0, 10),
            "sentiment": random.choice(["positive", "neutral", "negative"])
        }
