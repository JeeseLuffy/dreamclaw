import json
import urllib.error
import urllib.request
from dataclasses import dataclass
import os

import ollama


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


@dataclass
class PromptInput:
    system_prompt: str
    user_prompt: str
    temperature: float = 0.7
    max_tokens: int = 256
    timeout_seconds: int = 30


class BaseProvider:
    def generate(self, payload: PromptInput) -> str:
        raise NotImplementedError


class OllamaProvider(BaseProvider):
    def __init__(self, model: str, timeout_seconds: int = 30):
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = ollama.Client(timeout=timeout_seconds)

    def generate(self, payload: PromptInput) -> str:
        full_prompt = f"{payload.system_prompt}\n\n{payload.user_prompt}".strip()
        response = self.client.generate(
            model=self.model,
            prompt=full_prompt,
            options={"temperature": payload.temperature},
        )
        return response.get("response", "").strip()


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, model: str, endpoint: str, api_key: str, timeout_seconds: int = 30):
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(self, payload: PromptInput) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": payload.system_prompt},
                {"role": "user", "content": payload.user_prompt},
            ],
            "temperature": payload.temperature,
            "max_tokens": payload.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        raw = _http_post_json(self.endpoint, body, headers, timeout_seconds=self.timeout_seconds)
        choices = raw.get("choices", [])
        if not choices:
            raise ProviderRequestError("No choices returned from model.")
        content = choices[0].get("message", {}).get("content", "")
        return content.strip()


class AnthropicProvider(BaseProvider):
    def __init__(self, model: str, api_key: str, timeout_seconds: int = 30):
        self.model = model
        self.api_key = api_key
        self.endpoint = "https://api.anthropic.com/v1/messages"
        self.timeout_seconds = timeout_seconds

    def generate(self, payload: PromptInput) -> str:
        body = {
            "model": self.model,
            "max_tokens": payload.max_tokens,
            "system": payload.system_prompt,
            "messages": [{"role": "user", "content": payload.user_prompt}],
            "temperature": payload.temperature,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        raw = _http_post_json(self.endpoint, body, headers, timeout_seconds=self.timeout_seconds)
        content_blocks = raw.get("content", [])
        if not content_blocks:
            raise ProviderRequestError("No content returned from Anthropic.")
        text = " ".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")
        return text.strip()


class GoogleProvider(BaseProvider):
    def __init__(self, model: str, api_key: str, timeout_seconds: int = 30):
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(self, payload: PromptInput) -> str:
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        merged = f"{payload.system_prompt}\n\n{payload.user_prompt}".strip()
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": merged}],
                }
            ],
            "generationConfig": {
                "temperature": payload.temperature,
                "maxOutputTokens": payload.max_tokens,
            },
        }
        headers = {"Content-Type": "application/json"}
        raw = _http_post_json(endpoint, body, headers, timeout_seconds=self.timeout_seconds)
        candidates = raw.get("candidates", [])
        if not candidates:
            raise ProviderRequestError("No candidates returned from Google.")
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise ProviderRequestError("No parts returned from Google.")
        text = " ".join(part.get("text", "") for part in parts)
        return text.strip()


def _http_post_json(url: str, payload: dict, headers: dict, timeout_seconds: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise ProviderRequestError(f"HTTP error {exc.code}: {error_text}") from exc
    except urllib.error.URLError as exc:
        raise ProviderRequestError(f"Network error: {exc.reason}") from exc
    except Exception as exc:
        raise ProviderRequestError(f"Request failed: {exc}") from exc


def build_provider(provider: str, model: str, timeout_seconds: int = 30) -> BaseProvider:
    provider_name = provider.lower()
    if provider_name == "ollama":
        return OllamaProvider(model=model, timeout_seconds=timeout_seconds)

    if provider_name == "openai":
        key = _require_env("OPENAI_API_KEY")
        return OpenAICompatibleProvider(
            model=model,
            endpoint="https://api.openai.com/v1/chat/completions",
            api_key=key,
            timeout_seconds=timeout_seconds,
        )

    if provider_name == "deepseek":
        key = _require_env("DEEPSEEK_API_KEY")
        return OpenAICompatibleProvider(
            model=model,
            endpoint="https://api.deepseek.com/v1/chat/completions",
            api_key=key,
            timeout_seconds=timeout_seconds,
        )

    if provider_name == "moonshot":
        key = _require_env("MOONSHOT_API_KEY")
        return OpenAICompatibleProvider(
            model=model,
            endpoint="https://api.moonshot.cn/v1/chat/completions",
            api_key=key,
            timeout_seconds=timeout_seconds,
        )

    if provider_name == "qwen":
        key = _require_env("QWEN_API_KEY")
        return OpenAICompatibleProvider(
            model=model,
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            api_key=key,
            timeout_seconds=timeout_seconds,
        )

    if provider_name == "anthropic":
        key = _require_env("ANTHROPIC_API_KEY")
        return AnthropicProvider(model=model, api_key=key, timeout_seconds=timeout_seconds)

    if provider_name in {"google", "gemini"}:
        key = _require_env("GOOGLE_API_KEY")
        return GoogleProvider(model=model, api_key=key, timeout_seconds=timeout_seconds)

    raise ProviderConfigurationError(f"Unsupported provider: {provider}")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ProviderConfigurationError(f"Missing required environment variable: {name}")
    return value
