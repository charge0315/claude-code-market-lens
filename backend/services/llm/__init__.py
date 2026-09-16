"""機能ごとに利用LLMプロバイダ（Anthropic/OpenAI/Gemini）を選択・併用するための共通層.

各プロバイダクライアント（`anthropic_client`/`openai_client`/`gemini_client`）は、
プロンプト文字列を受け取り構造化 JSON を返す共通シグネチャ（`provider.LLMProvider`）に
揃えてある。`registry.resolve_feature_provider`/`resolve_shadow_providers` が
`backend.config.settings` の機能別設定を読み、実際にどのクライアントを使うかを解決する。
"""

from __future__ import annotations
