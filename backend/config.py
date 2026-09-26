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
    # マルチLLM判定（🆕 P12）: Anthropic（公式パイプライン）と並行して Gemini にも同じ
    # 候補を判定させ、根拠・確度・買値/損切/売値を比較表示する。未設定なら機能自体が
    # 無効（`gemini_client.is_configured=False`）で、公式パイプラインには一切影響しない。
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-pro", validation_alias="GEMINI_MODEL")
    # OpenAI（ChatGPT）: マルチLLM対応（🆕）。他プロバイダと同じくキー未設定なら機能無効。
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.1", validation_alias="OPENAI_MODEL")

    # --- LLM プロバイダ選択（🆕、機能ごとに公式/シャドウを個別設定可能） ---
    # 「公式」= 実際の売買判定・ピック確定を左右するプロバイダ。既定は全て Anthropic
    # （導入前と同じ挙動を維持）。`services/llm/registry.py` がこれを読んで解決する。
    llm_provider_stock_pick: Literal["anthropic", "openai", "gemini"] = Field(
        default="anthropic", validation_alias="LLM_PROVIDER_STOCK_PICK"
    )
    llm_provider_portfolio_signal: Literal["anthropic", "openai", "gemini"] = Field(
        default="anthropic", validation_alias="LLM_PROVIDER_PORTFOLIO_SIGNAL"
    )
    llm_provider_eod_review: Literal["anthropic", "openai", "gemini"] = Field(
        default="anthropic", validation_alias="LLM_PROVIDER_EOD_REVIEW"
    )
    llm_provider_trend_analyzer: Literal["anthropic", "openai", "gemini"] = Field(
        default="anthropic", validation_alias="LLM_PROVIDER_TREND_ANALYZER"
    )
    # note_publish（🆕 日次noteドラフト生成）は公式/シャドウ設定UIには出さない（YAGNI、
    # `services/llm/types.py` 参照）。設定を変えたい場合は .env を直接編集する。
    llm_provider_note_publish: Literal["anthropic", "openai", "gemini"] = Field(
        default="anthropic", validation_alias="LLM_PROVIDER_NOTE_PUBLISH"
    )
    # news_sentiment（🆕 ニュース見出しセンチメント判定、隔離LLM呼び出し）も note_publish と同じく
    # 公式/シャドウ設定UIには出さない（比較表示の使い道が薄く、二重LLM呼び出しはコスト削減という
    # 導入目的と矛盾するため）。
    llm_provider_news_sentiment: Literal["anthropic", "openai", "gemini"] = Field(
        default="anthropic", validation_alias="LLM_PROVIDER_NEWS_SENTIMENT"
    )
    # 「シャドウ」= 公式パイプラインと同一プロンプトを並行判定させ、比較表示のみに使う
    # チャレンジャー（複数併用可）。既定は導入前の Gemini shadow 挙動と完全一致させる。
    llm_shadow_providers_stock_pick: Annotated[list[str], NoDecode] = Field(
        default=["gemini"], validation_alias="LLM_SHADOW_PROVIDERS_STOCK_PICK"
    )
    llm_shadow_providers_portfolio_signal: Annotated[list[str], NoDecode] = Field(
        default=["gemini"], validation_alias="LLM_SHADOW_PROVIDERS_PORTFOLIO_SIGNAL"
    )
    llm_shadow_providers_eod_review: Annotated[list[str], NoDecode] = Field(
        default=[], validation_alias="LLM_SHADOW_PROVIDERS_EOD_REVIEW"
    )
    llm_shadow_providers_trend_analyzer: Annotated[list[str], NoDecode] = Field(
        default=[], validation_alias="LLM_SHADOW_PROVIDERS_TREND_ANALYZER"
    )
    # 機能×プロバイダごとのモデル上書き（🆕、空文字＝上書き無し。その場合はプロバイダの
    # 既定モデル（`anthropic_model`/`openai_model`/`gemini_model`）にフォールバックする、
    # `services/llm/registry.py` の `resolve_model()` 参照）。ある機能で同じプロバイダを
    # 公式・シャドウ両方で使っていても、モデルは共通（機能×プロバイダで1つ）。
    llm_model_stock_pick_anthropic: str = Field(default="", validation_alias="LLM_MODEL_STOCK_PICK_ANTHROPIC")
    llm_model_stock_pick_openai: str = Field(default="", validation_alias="LLM_MODEL_STOCK_PICK_OPENAI")
    llm_model_stock_pick_gemini: str = Field(default="", validation_alias="LLM_MODEL_STOCK_PICK_GEMINI")
    llm_model_portfolio_signal_anthropic: str = Field(
        default="", validation_alias="LLM_MODEL_PORTFOLIO_SIGNAL_ANTHROPIC"
    )
    llm_model_portfolio_signal_openai: str = Field(default="", validation_alias="LLM_MODEL_PORTFOLIO_SIGNAL_OPENAI")
    llm_model_portfolio_signal_gemini: str = Field(default="", validation_alias="LLM_MODEL_PORTFOLIO_SIGNAL_GEMINI")
    llm_model_eod_review_anthropic: str = Field(default="", validation_alias="LLM_MODEL_EOD_REVIEW_ANTHROPIC")
    llm_model_eod_review_openai: str = Field(default="", validation_alias="LLM_MODEL_EOD_REVIEW_OPENAI")
    llm_model_eod_review_gemini: str = Field(default="", validation_alias="LLM_MODEL_EOD_REVIEW_GEMINI")
    llm_model_trend_analyzer_anthropic: str = Field(default="", validation_alias="LLM_MODEL_TREND_ANALYZER_ANTHROPIC")
    llm_model_trend_analyzer_openai: str = Field(default="", validation_alias="LLM_MODEL_TREND_ANALYZER_OPENAI")
    llm_model_trend_analyzer_gemini: str = Field(default="", validation_alias="LLM_MODEL_TREND_ANALYZER_GEMINI")
    llm_model_note_publish_anthropic: str = Field(default="", validation_alias="LLM_MODEL_NOTE_PUBLISH_ANTHROPIC")
    llm_model_note_publish_openai: str = Field(default="", validation_alias="LLM_MODEL_NOTE_PUBLISH_OPENAI")
    llm_model_note_publish_gemini: str = Field(default="", validation_alias="LLM_MODEL_NOTE_PUBLISH_GEMINI")
    llm_model_news_sentiment_anthropic: str = Field(default="", validation_alias="LLM_MODEL_NEWS_SENTIMENT_ANTHROPIC")
    llm_model_news_sentiment_openai: str = Field(default="", validation_alias="LLM_MODEL_NEWS_SENTIMENT_OPENAI")
    llm_model_news_sentiment_gemini: str = Field(default="", validation_alias="LLM_MODEL_NEWS_SENTIMENT_GEMINI")

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

    # --- PIT（point-in-time）特徴量スナップショット（🆕 P29） ---
    # `plans/03_システム設計` §3.7。日次収集タスクの on/off とスコープ、学習パネルへの
    # 投入可否・被覆率ゲート閾値。詳細は `plans/05_決定ログと未決事項.md` §3 #I〜#K
    # （2026-09-18 ユーザー確認: I はセンチメント keyword も全ユニバースへ拡大、
    # K はゲート閾値を厳格化）。
    pit_snapshot_enabled: bool = Field(default=True, validation_alias="PIT_SNAPSHOT_ENABLED")
    pit_snapshot_scope: Literal["universe", "candidates", "watchlist"] = Field(
        default="universe", validation_alias="PIT_SNAPSHOT_SCOPE"
    )
    # 🔧 2026-09-18: 既定 "candidates" → "universe" へ変更（#I 確定）。yfinance のニュース取得を
    # 東証全銘柄（約4000銘柄）へ毎日走らせるため、レート制限次第では収集完了まで時間を要する
    # （キャッシュ TTL 24h、`sentiment_analyzer._SENTIMENT_CACHE_TTL` のため翌日以降は既存銘柄分
    # の再取得コストは下がる）。
    pit_sentiment_scope: Literal["universe", "candidates", "watchlist"] = Field(
        default="universe", validation_alias="PIT_SENTIMENT_SCOPE"
    )
    # 🆕 2026-09-26: 待ち時間なしの連続取得（実測 約0.3秒/銘柄）で約200銘柄目に Yahoo から
    # HTTP 999 で遮断されたため、銘柄間に待ち時間を入れる。全ユニバースでは 0.5 秒 × 約4,450 銘柄
    # ≒ 37 分の上乗せになる（solo worker を占有する時間とのトレードオフ）。遮断が再発したら延ばす。
    pit_sentiment_request_interval_sec: float = Field(
        default=0.5, validation_alias="PIT_SENTIMENT_REQUEST_INTERVAL_SEC", ge=0.0
    )
    # 学習パネルへの PIT 列投入そのものの opt-in（既定 OFF、台帳が貯まるまで明示的に有効化しない）。
    pit_features_enabled: bool = Field(default=False, validation_alias="PIT_FEATURES_ENABLED")
    # 🔧 2026-09-18: 60営業日/50% → 120営業日/70% へ厳格化（#K 確定、ユーザーが安定重視を選択）。
    pit_min_coverage_days: int = Field(default=120, validation_alias="PIT_MIN_COVERAGE_DAYS", ge=1)
    pit_min_coverage_ratio: float = Field(default=0.7, validation_alias="PIT_MIN_COVERAGE_RATIO", ge=0.0, le=1.0)
    pit_asof_tolerance_bdays: int = Field(default=5, validation_alias="PIT_ASOF_TOLERANCE_BDAYS", ge=0)

    # --- ナレッジベース ベクトル検索（kb_creator、既存の外部サービス。任意） ---
    # 空文字（既定）なら無効（`knowledge_search_client.search_ticker_notes` が常に空リストを返す）。
    # ユーザーの Obsidian Vault を Qdrant でインデックス済みの別プロセスへの読み取り専用クライアント。
    kb_search_url: str = Field(default="", validation_alias="KB_SEARCH_URL")
    # 実測で約21秒/クエリ（kb_creator側のベクトル検索計算コスト）かかることが判明したため、
    # 十分な余裕を持たせた既定値にする（`plans/04_タスクリスト.md` P10）。
    kb_search_timeout_seconds: float = Field(default=30.0, validation_alias="KB_SEARCH_TIMEOUT_SECONDS", ge=0.1)

    # --- 継続学習 / モデルレジストリ ---
    # 自動昇格は既定 OFF。昇格は API 承認でのみ champion を差し替える。
    model_auto_promote: bool = Field(default=False, validation_alias="MODEL_AUTO_PROMOTE")
    # champion 昇格ゲートの最小ペーパー成績日数（P0 でユーザー確認済み: 20 営業日）。
    paper_min_days: int = Field(default=20, validation_alias="PAPER_MIN_DAYS", ge=1)
    # AIピック判定プロンプトの挑戦者（`picks/prompt.py` の PROMPT_VARIANTS、例 "persona-v1"）。
    # 空なら無効。有効時は公式と同じモデルで別プロンプトを並走させ、`is_shadow=1` で台帳化して
    # 昇格評価だけに使う（`inference/prompt_challenger.py`）。公式ピックには影響しない。
    pick_prompt_challenger: str = Field(default="", validation_alias="PICK_PROMPT_CHALLENGER")
    # 特徴量分布ドリフト（PSI）の警告閾値。0.2 超で drift_flag。
    drift_psi_threshold: float = Field(default=0.2, validation_alias="DRIFT_PSI_THRESHOLD", ge=0.0)

    # --- 銘柄別モデル日次学習バッチ（P9）。既定値は Market Lens の運用値を踏襲。
    # ml_pool/mid_term/short_term レーンと異なり、これらは品質ゲート合格で自動 champion 化
    # される（`per_ticker_training_service._apply_quality_gate`、ユーザー確認済みの例外運用）。
    training_xgboost_daily_limit: int = Field(default=200, validation_alias="TRAINING_XGBOOST_DAILY_LIMIT", ge=1)
    training_random_forest_daily_limit: int = Field(
        default=200, validation_alias="TRAINING_RANDOM_FOREST_DAILY_LIMIT", ge=1
    )
    training_lstm_daily_limit: int = Field(default=40, validation_alias="TRAINING_LSTM_DAILY_LIMIT", ge=1)
    training_transformer_daily_limit: int = Field(default=40, validation_alias="TRAINING_TRANSFORMER_DAILY_LIMIT", ge=1)
    # 銘柄別アンサンブル（`ml_score_provider.make_per_ticker_ensemble_provider`）に
    # LSTM/Transformer を含めるか。既定 False（xgboost/random_forest のみ）: torch 同期推論は
    # 銘柄あたり数百msかかり、ピック生成のバッチ処理（候補プール全体を都度スコアリング）では
    # 所要時間が成立しないため（Market Lens `recommender._ensemble_model_types` と同じ理由）。
    recommender_ensemble_include_dl: bool = Field(default=False, validation_alias="RECOMMENDER_ENSEMBLE_INCLUDE_DL")

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

    @field_validator(
        "cors_origins",
        "llm_shadow_providers_stock_pick",
        "llm_shadow_providers_portfolio_signal",
        "llm_shadow_providers_eod_review",
        "llm_shadow_providers_trend_analyzer",
        mode="before",
    )
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
