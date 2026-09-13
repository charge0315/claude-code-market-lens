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
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

# フィールド名 → .env の変数名 / 画面表示ラベル。
_MANAGED_KEYS: tuple[tuple[str, str, str], ...] = (
    ("anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic API キー（Claude / 公式パイプライン）"),
    ("gemini_api_key", "GEMINI_API_KEY", "Gemini API キー（マルチLLM判定、任意）"),
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
