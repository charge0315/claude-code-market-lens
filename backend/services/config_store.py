"""外部 API キー（`.env`）の読み取り専用マスク表示 + 永続化.

`backend.config.settings` は起動時に一度だけ読み込む frozen 設定オブジェクトのため、
ここで `.env` を書き換えても実行中の backend / celery worker・beat には反映されない
（反映には各プロセスの再起動が必要）。設定画面の「現在の状態」表示は再起動なしで
直近の保存内容を反映できるよう、`settings` ではなく `os.environ` を直接参照する
（起動時の `load_dotenv()` で最初から同期しており、`update_env_keys` も保存の都度
 `os.environ` を更新するため、プロセス内では常に最新の保存値と一致する）。
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

# フィールド名 → .env の変数名 / 画面表示ラベル。
_MANAGED_KEYS: tuple[tuple[str, str, str], ...] = (
    ("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic API キー（Claude）"),
    ("openai_api_key", "OPENAI_API_KEY", "OpenAI API キー（ChatGPT）"),
    ("gemini_api_key", "GEMINI_API_KEY", "Gemini API キー"),
    ("jquants_api_key", "JQUANTS_API_KEY", "J-Quants API キー（東証公式データ補完）"),
)


def _mask(value: str) -> str:
    """末尾4文字だけ残してマスクする（生値は絶対に露出しない）."""
    if len(value) <= 4:
        return "•" * len(value)
    return f"{'•' * (len(value) - 4)}{value[-4:]}"


def get_api_key_status() -> list[dict[str, object]]:
    """設定画面向けの状況一覧（マスク済み）を返す."""
    rows: list[dict[str, object]] = []
    for field, env_name, label in _MANAGED_KEYS:
        value = os.environ.get(env_name, "")
        rows.append(
            {
                "key": field,
                "label": label,
                "configured": bool(value),
                "masked_value": _mask(value) if value else None,
            }
        )
    return rows


def env_name_for_field(field: str) -> str | None:
    """フィールド名（`anthropic_api_key` 等）から .env の変数名を引く."""
    for f, env_name, _label in _MANAGED_KEYS:
        if f == field:
            return env_name
    return None


def _validate_value(value: str) -> None:
    """`.env` への行インジェクションを防ぐ最小限の検証."""
    if "\n" in value or "\r" in value:
        raise ValueError("APIキーに改行は含められません")


# --- LLM プロバイダ選択（🆕、機能ごとの公式/シャドウ設定。`backend.config.Settings` の
#     `llm_provider_*`/`llm_shadow_providers_*` と1対1対応、.env永続化・反映は再起動後）。
_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic（Claude）",
    "openai": "OpenAI（ChatGPT）",
    "gemini": "Gemini",
}
_PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
# プロバイダの既定モデル env 変数名と `backend/config.py` のフィールド default（フォールバック値）。
_PROVIDER_DEFAULT_MODEL_ENV: dict[str, tuple[str, str]] = {
    "anthropic": ("ANTHROPIC_MODEL", "claude-sonnet-5"),
    "openai": ("OPENAI_MODEL", "gpt-5.1"),
    "gemini": ("GEMINI_MODEL", "gemini-2.5-pro"),
}
# 設定画面のモデル選択欄に出す代表的なモデル（プリセット、自由入力も併用可）。
# モデル名は頻繁に更新されるため、ここに無いモデルも自由入力で指定できる。
_PROVIDER_MODEL_PRESETS: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-5-5",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "claude-fable-5-1",
    ],
    "openai": ["gpt-5.1"],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash"],
}
_FEATURE_LABELS: dict[str, str] = {
    "stock_pick": "AIピック判定",
    "portfolio_signal": "ポートフォリオ売買判定",
    "eod_review": "EODレビュー",
    "trend_analyzer": "トレンド抽出",
}
# フィールド名 → (公式プロバイダの env 変数名, シャドウプロバイダ一覧の env 変数名, 既定公式, 既定シャドウ)。
# 既定値は `backend/config.py` のフィールド default と一致させ、未設定時の実際の動作と揃える。
_FEATURE_PROVIDER_ENV: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "stock_pick": ("LLM_PROVIDER_STOCK_PICK", "LLM_SHADOW_PROVIDERS_STOCK_PICK", "anthropic", ("gemini",)),
    "portfolio_signal": (
        "LLM_PROVIDER_PORTFOLIO_SIGNAL",
        "LLM_SHADOW_PROVIDERS_PORTFOLIO_SIGNAL",
        "anthropic",
        ("gemini",),
    ),
    "eod_review": ("LLM_PROVIDER_EOD_REVIEW", "LLM_SHADOW_PROVIDERS_EOD_REVIEW", "anthropic", ()),
    "trend_analyzer": ("LLM_PROVIDER_TREND_ANALYZER", "LLM_SHADOW_PROVIDERS_TREND_ANALYZER", "anthropic", ()),
}

# 機能×プロバイダごとのモデル上書き env 変数名（`backend/config.py` の `llm_model_*` と1対1対応）。
_MODEL_OVERRIDE_ENV: dict[tuple[str, str], str] = {
    ("stock_pick", "anthropic"): "LLM_MODEL_STOCK_PICK_ANTHROPIC",
    ("stock_pick", "openai"): "LLM_MODEL_STOCK_PICK_OPENAI",
    ("stock_pick", "gemini"): "LLM_MODEL_STOCK_PICK_GEMINI",
    ("portfolio_signal", "anthropic"): "LLM_MODEL_PORTFOLIO_SIGNAL_ANTHROPIC",
    ("portfolio_signal", "openai"): "LLM_MODEL_PORTFOLIO_SIGNAL_OPENAI",
    ("portfolio_signal", "gemini"): "LLM_MODEL_PORTFOLIO_SIGNAL_GEMINI",
    ("eod_review", "anthropic"): "LLM_MODEL_EOD_REVIEW_ANTHROPIC",
    ("eod_review", "openai"): "LLM_MODEL_EOD_REVIEW_OPENAI",
    ("eod_review", "gemini"): "LLM_MODEL_EOD_REVIEW_GEMINI",
    ("trend_analyzer", "anthropic"): "LLM_MODEL_TREND_ANALYZER_ANTHROPIC",
    ("trend_analyzer", "openai"): "LLM_MODEL_TREND_ANALYZER_OPENAI",
    ("trend_analyzer", "gemini"): "LLM_MODEL_TREND_ANALYZER_GEMINI",
}


def _resolve_model(feature: str, provider: str) -> str:
    """機能×プロバイダで実際に使われるモデル（上書き優先、無ければプロバイダ既定値）を返す."""
    override = os.environ.get(_MODEL_OVERRIDE_ENV[(feature, provider)])
    return override or _provider_default_model(provider)


def _provider_default_model(provider: str) -> str:
    """プロバイダの現在の既定モデル（.env 由来、未設定なら config.py のフィールド default）を返す."""
    env_name, fallback = _PROVIDER_DEFAULT_MODEL_ENV[provider]
    return os.environ.get(env_name) or fallback


def get_llm_provider_options(fetched_models: Mapping[str, list[str]] | None = None) -> list[dict[str, object]]:
    """選択肢として提示する全プロバイダの一覧（APIキー設定状況・既定モデル・モデル候補つき）を返す.

    `fetched_models` は公式モデル一覧APIの取得結果（`services/llm/model_catalog.py`）。
    取得できたプロバイダはそれを候補にし、取得できなかったプロバイダは固定プリセットへフォールバックする。
    """
    fetched = fetched_models or {}
    return [
        {
            "value": provider,
            "label": label,
            "configured": bool(os.environ.get(_PROVIDER_KEY_ENV[provider], "")),
            "default_model": _provider_default_model(provider),
            "model_presets": list(fetched.get(provider) or _PROVIDER_MODEL_PRESETS[provider]),
            "model_source": "api" if fetched.get(provider) else "preset",
        }
        for provider, label in _PROVIDER_LABELS.items()
    ]


def get_llm_provider_settings() -> list[dict[str, object]]:
    """機能ごとの現在の公式/シャドウプロバイダ設定（.env 由来、未設定なら既定値）を返す."""
    rows: list[dict[str, object]] = []
    for feature, (primary_env, shadow_env, default_primary, default_shadow) in _FEATURE_PROVIDER_ENV.items():
        primary = os.environ.get(primary_env) or default_primary
        shadow_raw = os.environ.get(shadow_env)
        shadow = (
            [s.strip() for s in shadow_raw.split(",") if s.strip()] if shadow_raw is not None else list(default_shadow)
        )
        rows.append(
            {
                "feature": feature,
                "label": _FEATURE_LABELS[feature],
                "primary_provider": primary,
                "shadow_providers": shadow,
                "models": {provider: _resolve_model(feature, provider) for provider in _PROVIDER_LABELS},
            }
        )
    return rows


def env_updates_for_llm_provider(
    feature: str,
    *,
    primary_provider: str | None,
    shadow_providers: Sequence[str] | None,
    models: dict[str, str] | None = None,
) -> dict[str, str]:
    """指定機能の更新差分を .env 変数名 → 値の dict にして返す（`update_env_keys` にそのまま渡せる）.

    `models` は provider_id → 希望モデル文字列。プロバイダの既定モデルと同じ値を指定した場合も
    明示的な上書きとして保存する（将来プロバイダの既定モデルを変更しても、この機能の挙動を
    変えたくない、というのが自然な期待のため）。空文字を指定すると上書きを解除し既定へ戻す。
    """
    if feature not in _FEATURE_PROVIDER_ENV:
        raise ValueError(f"未知の機能です: {feature}")
    primary_env, shadow_env, _default_primary, _default_shadow = _FEATURE_PROVIDER_ENV[feature]
    updates: dict[str, str] = {}
    if primary_provider is not None:
        updates[primary_env] = primary_provider
    if shadow_providers is not None:
        updates[shadow_env] = ",".join(shadow_providers)
    if models is not None:
        for provider, model in models.items():
            if (feature, provider) not in _MODEL_OVERRIDE_ENV:
                raise ValueError(f"未知のプロバイダです: {provider}")
            updates[_MODEL_OVERRIDE_ENV[(feature, provider)]] = model
    return updates


def update_env_keys(updates: dict[str, str]) -> None:
    """`.env` の該当行を更新する（`updates` は env 変数名 → 新しい値。空文字で未設定に戻す）.

    既存の行順・コメント・その他の変数はそのまま保持し、該当行だけ置き換える。
    見つからなければ末尾へ追記する。現在プロセスの `os.environ` も合わせて更新し、
    保存直後の GET が最新の状態を返せるようにする（実際の設定反映は再起動後）。
    """
    for value in updates.values():
        _validate_value(value)

    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() if _ENV_PATH.exists() else []
    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        name = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if name is not None and name in remaining:
            new_lines.append(f"{name}={remaining.pop(name)}")
        else:
            new_lines.append(line)
    for name, value in remaining.items():
        new_lines.append(f"{name}={value}")

    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    for env_name, value in updates.items():
        os.environ[env_name] = value
