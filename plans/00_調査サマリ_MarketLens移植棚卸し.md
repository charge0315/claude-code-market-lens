# P0 調査サマリ — Market Lens 再利用モジュール棚卸し

> 対象: 新規プロジェクト **Alpha Forge**（`C:\Users\charg\myWorkspace\claude-code-market-lens`）
> 再利用元: **Market Lens**（`C:\Users\charg\myWorkspace\market-lens`）
> 作成日: 2026-09-10 / 前提: 構築プロンプト `新規プロジェクト構築プロンプト.md`

---

## 1. 結論（サマリ）

Market Lens は Alpha Forge が必要とする機能の **上位互換に近い実装をすでに保有**している。
4分析スコアリング・3値ブラケット付き AI ピック・デイトレ候補・ピック結末スコアカード・
予測精度記録・評価指標（IC / 較正 / Brier）・日次学習バッチ（xgboost/RF/LSTM/Transformer）・
断面プールモデル・トレンド Agent・J-Quants/yfinance 取得層・ニュース digest（frontmatter のみ）・
銘柄ナレッジ注入（frontmatter のみ）・アプリ内通知・HITL の AI 運用ポートフォリオが揃っている。

**移植を第一選択**とし、Alpha Forge 固有の新規実装は次の 6 領域に集中する:

| # | 新規領域 | Market Lens の現状 |
|:--|:--|:--|
| N1 | **モデルレジストリ + champion/challenger + shadow 推論 + 昇格ゲート（提案のみ）** | `model_registry` テーブルはあるが「最新1行を読む」だけ。champion/challenger の概念・shadow 並走・昇格判定ログなし |
| N2 | **統合 Prediction Ledger**（両ホライズン横断・`feature_snapshot` 完全版・`source_contributions`） | `stock_pick_runs` / `pick_outcomes` / `predictions` が別々。特徴量スナップショットは部分的 |
| N3 | **確度の事後較正（isotonic / Platt）を UI 出力前に常時適用** | 較正誤差の「計測」はある（`eval_metrics`）が、確度そのものの再較正パイプラインはない |
| N4 | **AI 思考のリアルタイム可視化**（推論ステージ化・SSE/WebSocket・Thinking パネル・DAG ビュー・`inference_traces` 永続化 & リプレイ） | 該当機能なし。バックエンドに WebSocket/SSE 実装なし |
| N5 | **ドリフト検知（PSI）+ 再学習トリガの体系化**（定期 + ドリフト + 直近精度劣化） | 定期学習バッチはあるが PSI ドリフト検知・精度劣化トリガはなし |
| N6 | **Web Push（VAPID）** | `notification_service` はアプリ内通知のみ（「外部通知連携は行わない」と明記） |

その他の差分（軽微・設定レベル）:

- ポート: backend `8001→8002` / frontend `3000→3001`
- Vault: ニュース源が Market Lens は `News/<カテゴリ>/YYYYMMDD_*.md`、Alpha Forge は `Daily/YYYY-MM-DD.md`（frontmatter のみ）。銘柄ノートは両者とも `10_Stock/Tickers/<code>_<name>.md`（互換）
- 四季報: Alpha Forge は当面スタブ（`SHIKIHO_ENABLED=false`）。fundamental は Vault `Tickers/*.md` frontmatter + J-Quants で代替
- 多重ホライズン決着: Market Lens のピック結末は単一トリプルバリア。Alpha Forge は短期 3 営業日 / 中長期 20・60 営業日の複数ホライズン

---

## 2. モジュール別 移植判定

凡例: ⭐移植（ほぼそのまま） / 🔧移植+改修 / 🆕新規 / ❌対象外

### 2.1 データ取得層

| モジュール | 行数 | 判定 | 備考 |
|:--|--:|:--|:--|
| `services/jquants_client.py` | 401 | ⭐ | V2 認証・リトライ・サーキットブレーカ完備。そのまま移植 |
| `services/jquants_errors.py` | – | ⭐ | 型付き例外 |
| `services/data_fetcher.py` | 314 | ⭐ | yfinance 取得・キャッシュ・銘柄検索。5分足はデイトレ用 |
| `services/data_fetcher_errors.py` | – | ⭐ | |
| `services/ranking_service.py` | 484 | ⭐ | 全銘柄一括取得（`/equities/bars/daily` date のみ）。候補プール生成の土台 |
| `services/macro_features.py` | – | 🔧 | `^VIX` 代替（日経VI）。Market Lens 踏襲 |
| `services/trend/collector.py` `analyzer.py` `context.py` `sync_service.py` | 140/212/–/169 | ⭐ | Trend Tracking Agent。構造化データのみ注入 |
| `services/trend_service.py` | 274 | ⭐ | 業種別週次トレンド集計 |
| `services/cache.py` | 207 | ⭐ | |
| `services/circuit_breaker.py` `rate_limit.py` | – | ⭐ | |
| `services/trading_calendar.py` `jst_time.py` | –/– | ⭐ | JST・東証営業日カレンダー。ドメイン厳守事項 |

### 2.2 Obsidian Vault 連携

| モジュール | 行数 | 判定 | 備考 |
|:--|--:|:--|:--|
| `services/brand_notes_service.py` | 253 | ⭐ | `10_Stock/Tickers/<code>_<name>.md` の **frontmatter のみ**抽出。Alpha Forge の env `VAULT_ROOT` / `BRAND_NOTES_DIR` にマップ |
| `services/news_digest_service.py` | 260 | 🔧 | 読み取り元を `News/<カテゴリ>/*` → `Daily/YYYY-MM-DD.md` frontmatter に変更。frontmatter のみ方針は維持 |
| `services/daily_note_service.py` | 374 | 🔧 | Market Lens の出力ブロックとは**別マーカー**に限定。書き込みは事前確認。当面は read-only 運用でも可 |

### 2.3 スコアリング & ピック

| モジュール | 行数 | 判定 | 備考 |
|:--|--:|:--|:--|
| `services/technical_analysis.py` | 162 | ⭐ | ATR 等プリミティブ含む |
| `services/fundamental_analyzer.py` | – | 🔧 | 四季報スタブ期間は Vault frontmatter + J-Quants を主データ源に |
| `services/sentiment_analyzer.py` | 260 | ⭐ | |
| `services/recommender.py` | 755 | 🔧 | 4分析統合スコア・ハード除外 E1〜E3。`source_contributions` 出力を追加 |
| `services/ranking_service.py` | 484 | ⭐ | （再掲）候補プール |
| `services/stock_pick_service.py` | 896 | 🔧 | 中長期ピック。3値ブラケット + サーバ側検証は完成済み。Ledger 書き込み・trace 発行を追加。800行超のため分割しつつ移植 |
| `services/daytrade_service.py` | 393 | 🔧 | 短期（デイトレ）ピック。同上 |
| `services/theme_pick_service.py` | 358 | ⭐ | テーマ株ピック（発見用途、3値対象外） |
| `services/trend_picks_service.py` | 207 | ⭐ | トレンド業種別ピック |
| `services/signal_scan_service.py` ほか `signal_scan_*` | 386 ほか | 🔧 | 全銘柄スキャン（中断再開バッチ）。候補プールの母集団 |
| `services/factor_weight_service.py` | – | ⭐ | factor-IC 実測から重み算出（shadow） |
| `services/llm_tools.py` `anthropic_client.py` `anthropic_errors.py` | 394/627/– | ⭐ | forced tool-use・API コスト計測。LLM 構成は Market Lens 踏襲（確定） |

### 2.4 予測台帳・決着・評価（Alpha Forge の主目的）

| モジュール | 行数 | 判定 | 備考 |
|:--|--:|:--|:--|
| `services/pick_outcome_service.py` `pick_outcome_db.py` | 556/– | 🔧 | 後追い解決パターンは踏襲。**複数ホライズン**（3 / 20 / 60 営業日）へ拡張、MFE/MAE・到達順序・TOPIX 超過を記録 |
| `services/pick_simulation_service.py` | 426 | ⭐ | ピック執行シミュレーション（エクイティカーブ） |
| `services/prediction_accuracy_service.py` | 249 | 🔧 | `predictions.actual_close` 解決。統合 Ledger に寄せる |
| `services/eval_metrics.py` | 263 | ⭐ | IC・precision@k・Brier・skill。I/O なし純関数。そのまま移植 |
| `services/performance_ledger_service.py` | 214 | 🔧 | 戦略成績台帳。中長期/短期/合算のエクイティカーブへ |
| `services/signal_quality_service.py` `signal_scan_ic_service.py` `signal_scan_ic_db.py` | 241/311/153 | ⭐ | factor-IC 蓄積・シグナル品質 |
| `services/labeling.py` `ts_validation.py` | –/– | ⭐ | トリプルバリア・purged split（未来リーク排除の要）|
| `services/skill_metrics.py` | – | ⭐ | |
| `services/backtester.py` | 326 | ⭐ | ウォークフォワード検証の土台 |

### 2.5 継続学習 / ML

| モジュール | 行数 | 判定 | 備考 |
|:--|--:|:--|:--|
| `services/feature_engineering.py` | 354 | ⭐ | `feature_snapshot` の生成源 |
| `services/panel_feature_service.py` | 446 | ⭐ | 銘柄×営業日パネル |
| `services/ml_predictor.py` | 527 | ⭐ | XGBoost/RF、回帰 + トリプルバリア分類 |
| `services/dl/base.py` `lstm.py` `transformer.py` `networks.py` | 474 ほか | ⭐ | torch 系（CPU） |
| `services/ensemble_predictor.py` | 190 | ⭐ | 検証 RMSE 逆数で重み付け |
| `services/predictor_protocol.py` | – | ⭐ | Predictor Protocol |
| `services/pool_model.py` `pool_training_service.py` `pool_labeling.py` | –/319/– | ⭐ | 断面プールモデル（champion 候補の 1 系統） |
| `services/training_service.py` `training_batch_service.py` | 214/493 | ⭐ | 中断再開型 日次学習バッチ |
| `services/hyperparameter_tuner.py` | 159 | ⭐ | |
| **モデルレジストリ層（champion/challenger/shadow/昇格ゲート）** | – | 🆕 | **N1**。`model_registry` を拡張し、`model_champions` / `model_promotions` / `shadow_predictions` を新設 |
| **ドリフト検知（PSI）** | – | 🆕 | **N5** |
| `services/factor_weight_service.py` | – | ⭐ | （再掲）|
| 改善系 `improvement_*` | 159〜517 | 🔧 | 日次進化ループ（EVO-1〜6）。Alpha Forge は「今週何を学習したか」差分サマリに転用 |

### 2.6 ポートフォリオ & 通知

| モジュール | 行数 | 判定 | 備考 |
|:--|--:|:--|:--|
| `services/portfolio_service.py` | – | ⭐ | 保有登録（数量・取得単価・取得日） |
| `services/ai_portfolio_service.py` ほか `ai_portfolio_*`（allocation/costs/db/eod/macro/metrics/orders/risk） | 789 ほか | 🔧 | AI 運用（HITL・承認制・EOD レビュー・learned heuristics）。「継続保有/一部利確/損切/買い増し」判定 + 3値へ整理 |
| `services/risk_service.py` | 233 | ⭐ | |
| `services/notification_service.py` | – | 🔧 | アプリ内通知は踏襲。**Web Push（VAPID）アダプタを追加**（N6） |
| `services/alert_service.py` | – | ⭐ | 価格アラート |
| **Web Push 配信（`pywebpush` + VAPID 鍵管理 + 購読エンドポイント）** | – | 🆕 | **N6**。チャネルアダプタ差し替え可能な設計 |

### 2.7 AI 思考の可視化（全面新規）

| コンポーネント | 判定 | 備考 |
|:--|:--|:--|
| 推論オーケストレータ（ステージ DAG: 収集→サブスコア→LLM→合成→3値→検証） | 🆕 | **N4**。既存サービスを stage として束ねる薄い層 |
| SSE / WebSocket ルータ（トレース配信・通知 push） | 🆕 | FastAPI WebSocket |
| `inference_traces` 永続化 & リプレイ | 🆕 | |
| 特徴量レベル寄与（SHAP 相当）の bar 表示データ | 🔧 | `ml_predictor` に SHAP 出力を追加 |

### 2.8 基盤・横断

| モジュール | 判定 | 備考 |
|:--|:--|:--|
| `services/database.py`（1506行） | 🔧 | 分割しつつ移植。Alpha Forge のスキーマ差分を反映 |
| `backend/alembic/`（25 リビジョン） | 🔧 | `0001_baseline` 相当を Alpha Forge 用に再構成（統合 Ledger・レジストリ・traces を含む新 baseline） |
| `services/auth.py` `security_headers.py` `request_context.py` `api_cost.py` `task_registry.py` | ⭐ | |
| `backend/celery_app.py` `tasks.py` `config.py` `main.py` | 🔧 | ポート・タスク一覧・env を Alpha Forge 用に |
| `.github/workflows/ci.yml` | ⭐ | backend(ruff/black/mypy/bandit/pip-audit/pytest+cov/openapi) + frontend(eslint/tsc/jest/build) + e2e(playwright)。ほぼそのまま |
| frontend `src/components/ui/DataTable` `charts/` `sidebar/` `contexts/` `lib/api/` | ⭐ | プロ端末 UI 部品・API クライアント |
| frontend `src/app/tokens.css` | ⭐ | デザイントークン単一情報源（騰落色 赤=上げ / 緑=下げ） |
| frontend 各 `src/app/*` 画面 | 🔧 | dashboard / portfolio / mlops(→モデルラボ) / trend / stock-picks / daytrade を Alpha Forge の 5 画面へ再編。**銘柄詳細の思考トレース**は新規 |

---

## 3. 移植の進め方（各フェーズ共通ルール）

1. 新規実装の前に必ず対応する Market Lens モジュールを確認し、**移植で足りるか判断**。ゼロから書かない。
2. 移植時は Alpha Forge の CLAUDE.md 規約（ポート・Vault パス・800行上限・日本語コメント）へ合わせる。
3. 800行超（`database.py` 1506 / `stock_pick_service.py` 896 / `ai_portfolio_service.py` 789 / `recommender.py` 755）は移植と同時にモジュール分割する。
4. 移植したモジュールには「Market Lens `services/<name>.py` から移植、変更点: …」を docstring 冒頭に Why として残す。
5. テストも移植（Market Lens `backend/tests/`）。per-file の隔離 DB fixture 方針を踏襲。

---

## 4. 未確認事項（実装フェーズで都度確認）

- Market Lens の `.venv` を共有しない（別リポジトリのため Alpha Forge 専用 venv を作る）。
- `improvement_*`（日次進化ループ）を Alpha Forge にどこまで持ち込むか → P5 着手時に要判断（「今週の学習差分サマリ」に必要な範囲のみ）。
- `chat_service` / `whatif` / `backtest` ルータは Alpha Forge のスコープ外候補 → P1 で除外を確認。
