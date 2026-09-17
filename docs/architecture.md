# アーキテクチャ概観 — Alpha Forge

計画時点の設計判断は `plans/02_アーキテクチャ.md`（技術選定の理由）と `plans/03_システム設計.md`（テーブル・API 設計）にある。本ドキュメントは **実装完了後の "as-built" 概観**で、計画からの変更点も含めて現状を正確に記述する。フェーズごとの実装内容・移植可否判断・スコープ決定の詳細な経緯は `plans/04_タスクリスト.md` の各フェーズの記述を参照してください。

---

## 1. レイヤー構成

| レイヤー | 技術 | ポート |
|:--|:--|:--|
| frontend | Next.js 16 + TypeScript (strict) / Vanilla CSS | 3001 |
| backend | FastAPI + Python 3.11 | 8002 |
| DB | SQLite + Alembic（`backend/alembic/versions/`、head 追従） | — |
| 非同期 | Celery + Redis（DB 番号 4/5） | — |
| リアルタイム | SSE（推論トレース）/ WebSocket（通知） | — |

## 2. ディレクトリ構成（実装後）

```
backend/
├── main.py / celery_app.py / tasks.py / config.py
├── routers/       health / picks / trend / ledger / eval / registry /
│                  inference / portfolio / notify / stock / market / settings
├── services/
│   ├── data/      jquants / yfinance / trend / quote_service / market_indices_service
│   ├── vault/     brand_notes / news_digest / daily_note / knowledge_search_client
│   ├── scoring/   technical / fundamental / sentiment / recommender / ml_score_provider
│   ├── picks/     pipeline / bracket / gemini_picks / *_prompt
│   ├── ledger/    prediction_ledger / outcome_resolver / eval_service / weekly_learning_service
│   ├── learning/  feature_engineering / pool_model / pool_training_service / per_ticker_training_service
│   ├── registry/  promotion / drift / calibration / factor_weight_service / model_stats_service
│   ├── inference/ orchestrator（stage DAG）/ snapshot
│   ├── portfolio/ portfolio_service / risk_service / signal_service / eod_review_service
│   ├── notify/    notification_service / webpush
│   ├── config_store（🆕 P20、外部 API キーの .env マスク表示・永続化）
│   └── db/        テーブルごとの CRUD（SQLAlchemy async）
├── models/        Pydantic スキーマ（レイヤ対応）
└── tests/

frontend/src/
├── app/           dashboard / stock-detail / portfolio / model-lab / notifications / settings
├── components/    ui（🆕 Sparkline）/ layout / pipeline / dashboard（🆕 GeminiPicksBoard/AiPicksSection）/
│                  portfolio（🆕 AddHoldingModal/SellHoldingModal/StockSearchBox/SellHistoryTable）/
│                  notify / model-lab / stock-detail / settings
└── lib/           api/（REST クライアント）/ pipeline/ / realtime/（SSE・WS）/ push/ / jstDate.ts
```

計画時点（`plans/02`）との主な差分:
- `services/portfolio/ai_portfolio*` は実装していない。「AI が自前資金で仮想ポートフォリオを自動売買する」機能は、Alpha Forge の「実保有への HITL 提案のみ・自動約定なし」という設計思想とは相容れないため対象外とした（`plans/04_タスクリスト.md` P7a 参照）。
- frontend の `components/{charts,sidebar}/` は実際には機能別ディレクトリ（`dashboard/` `portfolio/` `model-lab/` `stock-detail/` `layout/`）に分かれている。
- P8 完了後（P9〜P26）にユーザー追加依頼で拡張: 銘柄別モデル自動学習（XGBoost/RandomForest/LSTM/Transformer）・ナレッジベース（Qdrant）検索統合・マルチLLM判定（Gemini を challenger として並行実行、`services/picks/gemini_picks.py` で独立一覧化）・外部 API キー設定画面（`services/config_store.py`）・ポートフォリオの銘柄検索追加/売却履歴（`portfolio_sell_history` テーブル）。UI 配色は CLAUDE.md 当初記載の near-black+ブルーから、ユーザー提示の参考デザインに合わせ最終的に明るいクリーム色（`tokens.css` 単一情報源）へ変更（`plans/04` P18/P21、`plans/05` §2b 参照）。

## 3. 推論オーケストレータの実行順（計画からの変更点）

`plans/02` の論理ビューは `③LLM overlay → ④synth` の順で記載しているが、実装は **`collect → subscore → synthesis → llm_overlay → bracket → verify`** の順（`services/inference/orchestrator.py`）。LLM への深掘りプロンプトが合成スコア（synthesis の結果）を埋め込む設計のため、synthesis が先に完了している必要がある。

## 4. 継続学習ループの実データフロー

1. **寄り付き前（JST 08:50/08:52）**: celery-beat がピック生成 → 推論オーケストレータが中長期・短期を実行 → 各ステージのトレースを `inference_traces` へ、最終ピックを `prediction_ledger` へ（`feature_snapshot` 完全版）。
2. **場中（9:00–15:30 JST、5分おき）**: 保有銘柄を AI が評価 → `portfolio_signals` へ `proposed` で記録 → `action != hold` なら `notifications` へ記録 + Web Push。人間が承認/却下/実約定報告するまでアプリは一切発注しない。
3. **大引け後（16:31 JST）**: 当日の `portfolio_signals` を集計し EOD レビュー（`eod_reviews`）を生成。学習教訓は要約として保存するのみで、翌日のプロンプトへの自動注入は行っていない（`plans/04` P7d のスコープ判断）。
4. **夜間（16:38/16:48 JST）**: 決着記録（複数ホライズン）→ 評価指標再集計（較正・IC・成績）。
5. **週次（日曜 03:30/03:45 JST）**: PSI ドリフト計測 → challenger 昇格評価（提案のみ、`model_promotions` へログ）。実際の champion 差し替えは `POST /api/registry/promotions/{id}/apply` の人手承認でのみ行う（`MODEL_AUTO_PROMOTE=false` 固定）。
6. **月次（1日 04:00 JST）**: 断面プール分類器（`lane="ml_pool"`）の再学習。

## 5. リアルタイム配信の実装方式

推論トレース（SSE）・通知（WebSocket）はいずれも **DB ポーリング方式**で配信する（`routers/inference.py` `routers/notify.py`）。ピック生成・保有監視は celery ワーカー、API サーバは別プロセスで動くため、プロセス内 pub/sub が使えず、これが最も簡潔な配信経路だった。ポーリング間隔は SSE が 1 秒、WebSocket が 1 秒（`_POLL_INTERVAL_SECONDS` / `_WS_POLL_INTERVAL_SECONDS`）。

## 6. セキュリティ境界（実装済み）

- 外部由来テキスト（Vault 本文・ニュース本文）は LLM プロンプトへ注入しない。注入するのは frontmatter / 構造化フィールドのみ（`services/vault/` `services/picks/*_prompt`）。
- 継続学習の教師信号は自分の実測値のみ。
- CSP は nonce ベース（`frontend/src/middleware.ts`）。
- Vault は読み取り専用。

---

より詳しい経緯（各フェーズで何を移植し、何を新規設計したか、その理由）は `plans/04_タスクリスト.md` を参照してください。運用（起動・監視・障害対応）は `docs/operations.md` を参照してください。
