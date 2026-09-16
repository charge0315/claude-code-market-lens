"""全 LLM プロバイダ共通の例外基底.

`anthropic_errors.AnthropicError` / `openai_errors.OpenAIError` / `gemini_errors.GeminiError` は
いずれもこの `LLMError` を継承する。機能ごとにプロバイダを動的解決する（`registry.py`）ため、
呼び出し側は具象プロバイダの例外型を静的に知らずに `except LLMError` で一律 catch できる。
"""

from __future__ import annotations


class LLMError(Exception):
    """全 LLM プロバイダクライアント共通の基底例外."""
