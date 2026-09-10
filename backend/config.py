"""アプリ全体の環境変数を集約し、起動時に即時検証する設定モジュール.

Market Lens `backend/config.py` の設計を踏襲（fail-fast、`frozen=True`、
`validation_alias` で既存 env 名を明示マップ）。Alpha Forge 固有の差分:

- ポートは backend 8002 / frontend 3001（Market Lens 8001 / 3000 と非衝突）。
- Vault は `VAULT_ROOT` 起点で `Tickers/` `Daily/` を導出（Market Lens は個別 env）。
- 四季報スタブ・モデル自動昇格 OFF・ペーパー最小日数・PSI 閾値・VAPID を追加。
- Redis DB 番号は Alpha Forge 専用（Market Lens と名前空間を分離）。
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_VAULT_ROOT = r"C:\Users\charg\Documents\Personal Space\10_Stock"


class Settings(BaseSettings):
    """全 env を集約した不変設定オブジェクト.

    frozen により生成後は変更不可。テストでは `model_copy(update=...)` で
    差し替えた新インスタンスをモジュール参照へ monkeypatch する。
    """

    model_config = SettingsConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    # --- 認証（必須。弱い鍵・空ハッシュを起動時に弾く） ---
    secret_key: str = Field(validation_alias="ML_SECRET_KEY", min_length=16)
    password_hash: str = Field(validation_alias="ML_PASSWORD_HASH", min_length=1)
    username: str = Field(default="admin", validation_alias="ML_USERNAME")

    # --- ネットワーク ---
    backend_port: int = Field(default=8002, validation_alias="BACKEND_PORT", ge=1, le=65535)
    frontend_port: int = Field(default=3001, validation_alias="FRONTEND_PORT", ge=1, le=65535)
    # NoDecode: pydantic-settings が env 値を JSON として先読みデコードするのを止め、
    # 下の `_split_csv`（mode="before"）へ生文字列を渡す。これで "a,b" 形式の
    # カンマ区切り env をそのまま受けられる（JSON 配列表記も引き続き許容）。
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3001", "http://127.0.0.1:3001"],
        validation_alias="ML_CORS_ORIGINS",
    )
    # 本番 https では true（HSTS を付与）、ローカル http では false 必須。
    cookie_secure: bool = Field(default=False, validation_alias="ML_COOKIE_SECURE")

    # --- 外部 API（任意。未設定でも起動でき、機能側が「未設定」を返す） ---
    jquants_api_key: str = Field(default="", validation_alias="JQUANTS_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    # LLM 構成は Market Lens 同一構成を踏襲（確定事項）。
    anthropic_model: str = Field(default="claude-sonnet-5", validation_alias="ANTHROPIC_MODEL")
    ai_portfolio_model: str = Field(default="claude-fable-5", validation_alias="AI_PORTFOLIO_MODEL")

    # --- DB ---
    database_url: str = Field(default="sqlite+aiosqlite:///./data/alpha_forge.db", validation_alias="DATABASE_URL")

    # --- Celery / Redis（Alpha Forge 専用 DB 番号で Market Lens と分離） ---
    celery_broker_url: str = Field(default="redis://127.0.0.1:6379/4", validation_alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://127.0.0.1:6379/5", validation_alias="CELERY_RESULT_BACKEND")

    # --- Obsidian Vault（読み取り専用が原則） ---
    vault_root: str = Field(default=_DEFAULT_VAULT_ROOT, validation_alias="VAULT_ROOT")
    # 空文字なら vault_root からの導出値を使う（後段の validator で解決）。
    brand_notes_dir: str = Field(default="", validation_alias="BRAND_NOTES_DIR")
    daily_notes_dir: str = Field(default="", validation_alias="DAILY_NOTES_DIR")

    # --- 四季報（当面スタブ） ---
    shikiho_enabled: bool = Field(default=False, validation_alias="SHIKIHO_ENABLED")

    # --- 継続学習 / モデルレジストリ ---
    # 自動昇格は既定 OFF。昇格は API 承認でのみ champion を差し替える。
    model_auto_promote: bool = Field(default=False, validation_alias="MODEL_AUTO_PROMOTE")
    # champion 昇格ゲートの最小ペーパー成績日数（P0 でユーザー確認済み: 20 営業日）。
    paper_min_days: int = Field(default=20, validation_alias="PAPER_MIN_DAYS", ge=1)
    # 特徴量分布ドリフト（PSI）の警告閾値。0.2 超で drift_flag。
    drift_psi_threshold: float = Field(default=0.2, validation_alias="DRIFT_PSI_THRESHOLD", ge=0.0)

    # --- 確度較正 ---
    calibration_method: Literal["auto", "isotonic", "platt", "identity"] = Field(
        default="auto", validation_alias="CALIBRATION_METHOD"
    )

    # --- Web Push（VAPID）。未設定なら push 配信は無効（アプリ内通知のみ） ---
    vapid_public_key: str = Field(default="", validation_alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field(default="", validation_alias="VAPID_PRIVATE_KEY")
    vapid_subject: str = Field(default="mailto:charge0315@outlook.com", validation_alias="VAPID_SUBJECT")

    # --- LLM コスト安全装置（目標ではない。自動適用しない） ---
    llm_daily_cost_limit_usd: float = Field(default=5.0, validation_alias="LLM_DAILY_COST_LIMIT_USD", ge=0.0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """ "a,b" 形式のカンマ区切り env を list へ変換する（JSON 配列表記も許容）."""
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def resolved_brand_notes_dir(self) -> Path:
        """銘柄ナレッジノートのディレクトリ（未指定なら `<VAULT_ROOT>/Tickers`）."""
        return Path(self.brand_notes_dir) if self.brand_notes_dir else Path(self.vault_root) / "Tickers"

    @property
    def resolved_daily_notes_dir(self) -> Path:
        """日次マーケットノートのディレクトリ（未指定なら `<VAULT_ROOT>/Daily`）."""
        return Path(self.daily_notes_dir) if self.daily_notes_dir else Path(self.vault_root) / "Daily"


# import 時に即時検証（fail-fast）。必須 env 欠落ならここで起動が止まる。
settings = Settings()
