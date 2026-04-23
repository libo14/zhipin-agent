from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


class LLMClient(Protocol):
    def invoke(self, prompt: Any) -> Any:
        ...


@dataclass
class MockAIMessage:
    content: str


class MockChatModel:
    """Small deterministic LLM stand-in for offline demos and tests."""

    def invoke(self, prompt: Any) -> MockAIMessage:
        if isinstance(prompt, list):
            text = "\n".join(str(item) for item in prompt)
        else:
            text = str(prompt)
        preview = text.replace("\n", " ")[:180]
        return MockAIMessage(content=f"[Mock LLM] 已根据输入生成结构化建议：{preview}")


def build_llm() -> LLMClient:
    """Build a LangChain chat model when credentials exist, otherwise use mock mode.

    Supported environment variables:
    - LLM_PROVIDER=mock|openai|siliconflow
    - LLM_MODEL, LLM_BASE_URL
    - OPENAI_API_KEY or SILICONFLOW_API_KEY
    """

    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider == "mock":
        return MockChatModel()

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return MockChatModel()

    if provider == "siliconflow":
        api_key = os.getenv("SILICONFLOW_API_KEY")
        base_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
        model = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V3")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        return MockChatModel()

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.2")),
    }
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def message_text(message: Any) -> str:
    """Extract text from LangChain AIMessage-like objects or plain strings."""

    if isinstance(message, str):
        return message
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return str(content)
