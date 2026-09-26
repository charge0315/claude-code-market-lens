"""各LLMプロバイダの公式「モデル一覧API」から、選択可能なモデル名を取得する.

設定画面のモデル選択プルダウン用。固定のプリセットではモデルの追加（例: Gemini の新世代）に
追従できないため、公式APIが返す一覧をそのまま候補にする。

- Anthropic: `GET https://api.anthropic.com/v1/models`（新しい順で返る）
- OpenAI:    `GET https://api.openai.com/v1/models`（音声・画像・埋め込み等の非テキスト生成モデルも
  返るため、本アプリの構造化JSON生成に使えない系統は名前で除外する）
- Gemini:    `GET https://generativelanguage.googleapis.com/v1beta/models`
  （`supportedGenerationMethods` に `generateContent` を含むものだけ）

APIキーは `.env` 由来の `os.environ` から読む（`config_store` と同じく、再起動前の
キー更新も一覧取得には即反映させるため）。キーは URL に載せずヘッダで渡し、ログにも出さない。
取得失敗・キー未設定時は `None` を返し、呼び出し側が固定プリセットへフォールバックする。
設定画面を開くたびに外部APIを叩かないよう、結果をプロセス内で TTL キャッシュする。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
# 成功時は1時間、失敗時は5分だけ結果を保持する（失敗時に毎回タイムアウトを待たせないため）。
_SUCCESS_TTL_SEC = 3600.0
_FAILURE_TTL_SEC = 300.0
# ページング上限（無限ループ防止の安全網。実際は1〜2ページで終わる）。
_MAX_PAGES = 20

# 本アプリは構造化JSONのテキスト生成にしか使わないため、それ以外の用途の系統を名前で除外する。
_NON_TEXT_MARKERS: tuple[str, ...] = (
    "embedding",
    "tts",
    "audio",
    "realtime",
    "transcribe",
    "whisper",
    "image",
    "dall-e",
    "moderation",
    "search",
    "live",
    "veo",
    "imagen",
    "sora",
    "robotics",
    "computer-use",
)
# Gemini API は画像(nano-banana)・音楽(lyria)・Gemma・エージェント系なども generateContent 対応として
# 返すが、本アプリの JSON スキーマ付き生成は Gemini 本体でのみ検証しているため `gemini-` 系に限る。
_GEMINI_TEXT_PREFIX = "gemini-"
_OPENAI_TEXT_PREFIXES: tuple[str, ...] = ("gpt-", "o1", "o3", "o4", "chatgpt-")

_cache: dict[str, tuple[float, list[str] | None]] = {}


def _is_text_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_TEXT_MARKERS)


async def _fetch_anthropic(client: httpx.AsyncClient, api_key: str) -> list[str]:
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    ids: list[str] = []
    params: dict[str, str | int] = {"limit": 1000}
    for _ in range(_MAX_PAGES):
        res = await client.get("https://api.anthropic.com/v1/models", headers=headers, params=params)
        res.raise_for_status()
        body = res.json()
        ids.extend(str(m["id"]) for m in body.get("data", []))
        if not body.get("has_more") or not body.get("last_id"):
            break
        params = {"limit": 1000, "after_id": str(body["last_id"])}
    return ids


async def _fetch_openai(client: httpx.AsyncClient, api_key: str) -> list[str]:
    res = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    res.raise_for_status()
    models = [m for m in res.json().get("data", []) if isinstance(m, dict)]
    # 一覧は順不同で返るため、新しいモデルが上に来るよう作成日時の降順に並べる。
    models.sort(key=lambda m: int(m.get("created") or 0), reverse=True)
    return [
        str(m["id"]) for m in models if str(m["id"]).startswith(_OPENAI_TEXT_PREFIXES) and _is_text_model(str(m["id"]))
    ]


async def _fetch_gemini(client: httpx.AsyncClient, api_key: str) -> list[str]:
    ids: list[str] = []
    params: dict[str, str | int] = {"pageSize": 1000}
    for _ in range(_MAX_PAGES):
        res = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
            params=params,
        )
        res.raise_for_status()
        body = res.json()
        for m in body.get("models", []):
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            name = str(m.get("name", "")).removeprefix("models/")
            if name.startswith(_GEMINI_TEXT_PREFIX) and _is_text_model(name):
                ids.append(name)
        token = body.get("nextPageToken")
        if not token:
            break
        params = {"pageSize": 1000, "pageToken": str(token)}
    # 名前の降順 = おおむね新しい世代が上（gemini-3.x → gemini-2.x）。
    return sorted(set(ids), reverse=True)


_FETCHERS: dict[str, tuple[str, Callable[[httpx.AsyncClient, str], Awaitable[list[str]]]]] = {
    "anthropic": ("ANTHROPIC_API_KEY", _fetch_anthropic),
    "openai": ("OPENAI_API_KEY", _fetch_openai),
    "gemini": ("GEMINI_API_KEY", _fetch_gemini),
}


async def fetch_models(provider: str) -> list[str] | None:
    """1プロバイダの選択可能なモデル名一覧を返す（キー未設定・取得失敗・空なら `None`）."""
    now = time.monotonic()
    cached = _cache.get(provider)
    if cached is not None and cached[0] > now:
        return cached[1]

    env_name, fetcher = _FETCHERS[provider]
    api_key = os.environ.get(env_name, "")
    if not api_key:
        return None  # キー未設定はキャッシュしない（設定直後に即取得できるように）

    result: list[str] | None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            result = list(dict.fromkeys(await fetcher(client, api_key))) or None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # 例外メッセージにはURL等が含まれうるがキーはヘッダ渡しのため含まれない。型名のみ残す。
        logger.warning("モデル一覧の取得に失敗: provider=%s error=%s", provider, type(exc).__name__)
        result = None

    ttl = _SUCCESS_TTL_SEC if result is not None else _FAILURE_TTL_SEC
    _cache[provider] = (now + ttl, result)
    return result


async def fetch_all_models() -> dict[str, list[str]]:
    """全プロバイダのモデル一覧を並列取得する（取得できたプロバイダだけを含む）."""
    providers = list(_FETCHERS)
    results = await asyncio.gather(*(fetch_models(p) for p in providers))
    return {p: models for p, models in zip(providers, results, strict=True) if models}


def clear_cache() -> None:
    """キャッシュを破棄する（APIキー更新時・テスト用）."""
    _cache.clear()
