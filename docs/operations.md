# 運用Runbook

本ドキュメントは Alpha Forge を実際に動かし続ける（起動・監視・障害対応・バックアップ）ための手順書です。設計判断の背景は `plans/02_アーキテクチャ.md` `plans/03_システム設計.md` を、フェーズごとの実装詳細・移植可否判断は `plans/04_タスクリスト.md` を参照してください。ここでは「今すぐ何をすればよいか」に絞って記述します。

対象読者: 本システムを自宅PC等で動かし続ける開発者本人（デスクトップ常駐・シングルユーザー構成が前提。CLAUDE.md 参照）。

---

## 1. 起動・停止

### 通常起動（手動）

以下 4 プロセスを手動で起動する。

```powershell
# 1. バックエンド（ポート 8002）
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002

# 2. Celery ワーカー（ピック生成・保有監視・学習バッチ・通知・EOD レビュー等の実処理。
#    Windows は --pool=solo 必須）
.venv\Scripts\celery.exe -A backend.celery_app worker --pool=solo --loglevel=info

# 3. Celery beat（定期実行スケジューラ。ワーカーとは別プロセス — Windows は
#    `worker -B`（beat 埋め込み）を拒否するため必ず分離する）
.venv\Scripts\celery.exe -A backend.celery_app beat --loglevel=info

# 4. フロントエンド（ポート 3001）
cd frontend && npm run build && npm start   # 本番相当
# cd frontend && npm run dev                 # 開発時
```

Redis はローカルで別途起動しておく（`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` の既定は `redis://127.0.0.1:6379/4` `/5`）。**Redis 未起動でもバックエンド自体は起動する**が、celery-beat 経由の自走機能（下記表）はすべて動かない。

停止は各プロセスを `Ctrl+C`。Celery ワーカーは実行中タスクの完了を待たず即終了する（再実行すればよい、DB は壊れない）。

### 簡易起動（まとめて起動/停止）

まとめて起動/停止するスクリプトを用意している。

```powershell
.\scripts\start.ps1   # 4プロセスをまとめてバックグラウンド起動
.\scripts\stop.ps1    # まとめて停止
```

### ログオン時の自動起動（🆕、ユーザー指示）

`AlphaForge-Autostart` というタスクスケジューラのタスクを登録すると、ログオン時に Alpha Forge が
自動起動する。単に `start.ps1` を呼ぶのではなく、まず依存サービス（後述）の起動を
`scripts\wait-for-kb-services.ps1` がポーリングで待ってから `start.ps1` を実行する
（`scripts\start-with-dependencies.ps1` 経由）。

起動順序: **Docker Desktop → Redis サービス → Vector API サービス → Vector Watcher → Alpha Forge**。
後の3つは `obsidian-knowledge-base-creator` プロジェクトが管理する既存のログオン時タスク
（`KB-Service-Redis` / `KB-Service-VectorApi` / `KB-Vault-VectorWatch`）で、Alpha Forge の
ナレッジベース検索（`KB_SEARCH_URL`）が使う Vector API と同じもの。Task Scheduler には
「他タスク完了後に起動」というトリガーが無いため、各サービスの実際の生存確認
（Docker daemon 応答 / `127.0.0.1:6379` 疎通 / `http://127.0.0.1:8077` 疎通 /
`KB-Vault-VectorWatch` タスクの Running 状態）をポーリングして順序を保証している。
いずれかがタイムアウトしても警告を出すだけで起動は続行する（フェイルソフト、
Redis/KB 系が落ちていても Alpha Forge 自体は起動できるようにするため）。

```powershell
# 登録（管理者権限の pwsh で1回だけ）
.\scripts\register-startup-task.ps1

# 解除
.\scripts\register-startup-task.ps1 -Unregister

# 今すぐ動作確認（既に手動で起動中のプロセスがあると .run\pids.json 衝突で失敗するので注意）
Start-ScheduledTask -TaskName AlphaForge-Autostart
```

タスクは「ログオン時」に発火する（`KB-Service-*` / `KB-Vault-VectorWatch` と同じトリガー種別）。
PC 起動＝ログオンではない環境では `-AtStartup` 版に読み替えること。`start.ps1` は
`.run\pids.json` が残っていると「起動中」とみなして exit 1 する。前回が正常終了
（`stop.ps1`）していれば問題ないが、クラッシュ後は手動で `.run\pids.json` を削除してから
ログオンし直すこと。

### 起動確認

```bash
curl http://localhost:8002/api/health   # liveness: プロセスが生きているか
curl http://localhost:8002/health        # readiness: DB/Redis まで含めた疎通確認
```

### 自走スケジュール（celery-beat、`backend/celery_app.py` の `_BEAT_SCHEDULE` が単一情報源）

時刻はすべて JST。beat の内部設定は UTC 固定のため、コード上は UTC 換算値で書かれている点に注意（本表はすでに JST 換算済み）。

| 時刻 / 周期 | タスク | 内容 |
|---|---|---|
| 平日 07:30 | `run_picks_task("mid_term")` | 中長期ピック生成（🔧 P28、当初 08:50 から前倒し。下記参照） |
| 平日 07:32 | `run_picks_task("short_term")` | 短期ピック生成（🔧 P28、当初 08:52 から前倒し。`--pool=solo` の直列ワーカーでは2分ずらしても順番待ちになるだけで二重占有回避の効果は無いが、ピック生成完了を早めるために時刻自体を前倒しした） |
| 平日 08:05 | `run_daily_note_draft_task` | 🆕 P28、note下書き自動生成（Obsidian/SingleHTML書き出しまで同タスク内で実行）。ピック生成完了を待てるだけの余裕を見て設定 |
| 平日 08:15 | `generate_vault_report_task` | 🆕 P28、個人用Vaultアーカイブレポート生成（note下書き生成の後、同じ台帳データから作成） |
| 毎日 16:38 | `resolve_pick_outcomes_task` | 未決着ピックの決着解決（複数ホライズン） |
| 毎日 16:48 | `update_eval_metrics_task` | 評価指標（較正・IC・成績）再集計 |
| 毎日 07:13/10:13/13:13/16:13 | `sync_trends_task` | Trend Tracking Agent 同期（TTL 3h） |
| 毎日 16:31 | `run_eod_review_task` | 大引け後レビュー生成（`portfolio_signals` 当日分の集計 + LLM 教訓抽出） |
| 場中5分おき（平日 9:00–15:30、内部ゲート） | `run_portfolio_monitor_task` | 保有銘柄の AI 売買タイミング判定（HITL 提案のみ、自動約定なし） |
| 常時5分おき | — | *(枠のみ。P5 以降で個別タスクを追加した箇所は上記に統合済み)* |
| 日曜 03:30 | `run_drift_check_task` | 特徴量分布ドリフト（PSI）週次計測 |
| 日曜 03:45 | `run_promotion_evaluation_task` | challenger 昇格判定（週次、提案のみ・自動昇格なし） |
| 毎月1日 04:00 | `run_pool_training_task` | 断面プール分類器（`lane="ml_pool"`）の月次再学習 |
| 毎時 xx:01-xx:56 の5分おき | `run_xgboost_training_batch_task` | 銘柄別 XGBoost モデルの日次学習バッチ（東証全銘柄を当日上限まで巡回） |
| 毎時 xx:03-xx:58 の5分おき | `run_random_forest_training_batch_task` | 銘柄別 RandomForest モデルの日次学習バッチ（xgboost と2分ずらして直列ワーカーの二重占有回避） |
| 毎時 xx:20 | `run_lstm_training_batch_task` | 銘柄別 LSTM モデルの日次学習バッチ（torch 学習のため1時間間隔） |
| 毎時 xx:50 | `run_transformer_training_batch_task` | 銘柄別 Transformer モデルの日次学習バッチ（torch 学習のため1時間間隔） |

🔧 `run_picks_task`・`run_portfolio_monitor_task` は `_is_trading_day_jst()`（`jpholiday` で祝日判定）で休場日を除外する（2026-09-20、`48354f5`）。上表の「平日」表記はこの2タスクに限り実質「取引日」（土日祝を除く）— beatのcrontab自体には`day_of_week`指定は無く、休場日でも起動はされるが内部で無害な早期returnをする。他のタスク（note下書き・Vaultレポート・決着解決・評価指標・トレンド同期・週次/月次バッチ等）は休場日ガードを持たず、crontab設定どおり毎日/毎週/毎月発火する（休場日は対象データが無いため実質no-opになるものが大半だが、個別に保証されているわけではない）。

**銘柄別モデル（P9）の champion 差し替えは人手承認を経ない**: 上記4タスクは品質ゲート
（held-out skill・既存 champion との再窓合わせ RMSE 比較）合格時に `model_champions`
（`lane=f"{model_type}:{ticker}"`）を自動差し替える（`promoted_by="quality_gate"`）。
`ml_pool`/`mid_term`/`short_term` レーン（`run_promotion_evaluation_task` が扱う人手承認ゲート）
とは意図的に別格の運用（ユーザー確認済み、`per_ticker_training_service.py` docstring 参照）。

**手で `.delay()` タスクを投入しない**（CLAUDE.md）。手動実行が必要な場合は対応する API（`POST /api/picks/run`、`POST /api/portfolio/signals/run`、`POST /api/portfolio/eod-review/run`、`POST /api/eval/run`、`POST /api/registry/promotions/evaluate`、`POST /api/notes/generate`（🆕 P28、note下書きの再生成）、`POST /api/vault-reports/generate`（🆕 P28）等）を使う。

**銘柄別モデルの手動学習トリガー（`POST /api/registry/training/run`、モデルラボ「今すぐ学習」）
は上記の `TRAINING_*_DAILY_LIMIT` を使わない**（🆕 P14、ユーザー確認済み）:
celery-beat の自動定期実行は5分/60分間隔の1firing予算に収める人為的な低い上限が必要だが、
手動トリガーは P13h でバックグラウンドタスク化済みのため HTTP タイムアウトに縛られず、
「未学習優先→最も学習が古い順」で東証全銘柄を対象にいけるところまで学習する
（`per_ticker_training_service.manual_full_run_overrides`）。暴走を止める安全網としての
時間予算のみを設ける: xgboost/random_forest は6時間、lstm/transformer は12時間
（`_MANUAL_FULL_RUN_DURATION_SECONDS`/`_MANUAL_FULL_RUN_DL_DURATION_SECONDS`、
設定不可の固定値）。中断された場合も `training_batch_runs`（当日試行済み）+
`model_registry.trained_at`（銘柄ごとの最終学習日時）を毎回読み直す既存設計により、
再度ボタンを押すだけで続きから再開する。

---

## 2. 環境変数

`.env.example` をコピーして `.env` を作成する（Git 管理外）。

| 変数 | 必須 | 既定値 | 用途 |
|---|:---:|---|---|
| `ML_SECRET_KEY` | ✅ | なし（16文字未満は起動時エラー） | 旧設計の認証基盤向け設定スロットの名残。Alpha Forge は未認証（単一ユーザー・デスクトップ常駐前提、CLAUDE.md）だが `Settings()` の fail-fast 検証は残しているため値の設定自体は必須 |
| `ML_PASSWORD_HASH` | ✅ | なし（空は起動時エラー） | 同上（現状ログイン機能では未使用。上記と同じ理由で必須） |
| `ML_USERNAME` | – | `admin` | 同上（未使用） |
| `BACKEND_PORT` / `FRONTEND_PORT` | – | `8002` / `3001` | 他のローカルサービスと競合しないよう選定したポート |
| `ML_CORS_ORIGINS` | – | `http://localhost:3001,http://127.0.0.1:3001` | CORS 許可オリジン |
| `BACKEND_PROXY_TARGET` | – | `http://127.0.0.1:8002` | frontend の `/api` `/ws` リライト先（Next.js サーバのみ参照） |
| `ML_COOKIE_SECURE` | – | `false` | 本番 https では `true` 必須 |
| `JQUANTS_API_KEY` | – | 空（yfinance にフォールバック） | J-Quants API キー |
| `ANTHROPIC_API_KEY` | – | 空（AI 機能が `not_configured` を返す） | Claude API キー（ピック生成・ポートフォリオ判定・EOD レビューの LLM 深掘りに使用） |
| `ANTHROPIC_MODEL` | – | `claude-sonnet-5` | 使用する Claude モデル ID |
| `LLM_DAILY_COST_LIMIT_USD` | – | `5.0` | LLM コストの安全装置（目標ではない、CLAUDE.md）。超過時の挙動は `services/api_cost` 参照 |
| `GEMINI_API_KEY` | – | 空（マルチLLM判定が無効） | Gemini API キー（🆕 P12）。設定すると公式パイプライン（Anthropic）と並行して比較用の shadow 判定を `shadow_predictions` へ記録する。未設定でも公式パイプラインには一切影響しない |
| `GEMINI_MODEL` | – | `gemini-2.5-pro` | 使用する Gemini モデル ID |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | – | 空 / – | OpenAI API キー・モデル ID（🆕 P27、`services/openai_client.py`）。3プロバイダ目として追加 |
| `LLM_PROVIDER_<FEATURE>` / `LLM_SHADOW_PROVIDERS_<FEATURE>` | – | 既定は導入前と同一動作（公式=`anthropic`、shadowは stock_pick/portfolio_signal のみ `gemini`） | 🆕 P27、機能（`stock_pick`/`portfolio_signal`/`eod_review`/`trend_analyzer`/`note_publish`）ごとに公式・シャドウのLLMプロバイダを選択（`services/llm/registry.py`、詳細は `plans/05_決定ログと未決事項.md` §2c）。`/settings` 画面からも編集可（`LLMProviderPanel.tsx`） |
| `LLM_MODEL_<FEATURE>_<PROVIDER>` | – | 空（プロバイダ既定モデルを使用） | 🆕 P27、機能×プロバイダごとの使用モデルを個別上書き |
| `DATABASE_URL` | – | `sqlite+aiosqlite:///./data/alpha_forge.db` | DB 接続先（PostgreSQL 移行可能な設計） |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | – | `redis://127.0.0.1:6379/4` `/5` | Celery（他サービスと衝突しないよう DB 番号を分離） |
| `VAULT_ROOT` | – | `Personal Space/10_Stock` | Obsidian Vault ルート（読み取り専用が原則） |
| `BRAND_NOTES_DIR` / `DAILY_NOTES_DIR` | – | 空（`VAULT_ROOT` から導出） | 銘柄ナレッジ / 日次マーケットノートのディレクトリ |
| `SHIKIHO_ENABLED` | – | `false` | 四季報連携（当面スタブ） |
| `KB_SEARCH_URL` | – | 空（機能無効） | ナレッジベース・ベクトル検索（kb_creator、既存の外部サービス）への接続先。未設定なら関連ノート無しにフォールバック |
| `KB_SEARCH_TIMEOUT_SECONDS` | – | `30.0` | 上記のタイムアウト秒（kb_creator は実測 約21秒/クエリかかるため余裕を持たせている） |
| `MODEL_AUTO_PROMOTE` | – | `false` | **常に false 運用**。昇格は `POST /api/registry/promotions/{id}/apply` の人手承認でのみ行う |
| `PAPER_MIN_DAYS` | – | `20` | champion 昇格ゲートの最小ペーパー成績日数 |
| `DRIFT_PSI_THRESHOLD` | – | `0.2` | PSI ドリフト警告閾値 |
| `TRAINING_XGBOOST_DAILY_LIMIT` / `TRAINING_RANDOM_FOREST_DAILY_LIMIT` | – | `200` / `200` | 銘柄別モデル日次学習バッチ（P9）の当日学習上限銘柄数。**celery-beat の自動定期実行のみに適用**（🔧 P14、下記参照） |
| `TRAINING_LSTM_DAILY_LIMIT` / `TRAINING_TRANSFORMER_DAILY_LIMIT` | – | `40` / `40` | 同上（torch 学習のため低め） |
| `CALIBRATION_METHOD` | – | `auto` | 確度較正方式（`auto`/`isotonic`/`platt`/`identity`） |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | – | 空（Push 配信は無効、アプリ内通知のみ） | Web Push 用 VAPID 鍵。`npx web-push generate-vapid-keys` で生成 |

必須変数（`ML_SECRET_KEY`, `ML_PASSWORD_HASH`）はどちらか欠けると `backend/config.py` の `Settings()` が起動時に例外を投げる（フェイルファスト設計）。ローカル動作確認だけであれば任意のダミー値（32文字以上の `ML_SECRET_KEY` と bcrypt 形式の `ML_PASSWORD_HASH`）で起動できる。

**外部 API キー（`ANTHROPIC_API_KEY`/`GEMINI_API_KEY`/`JQUANTS_API_KEY`）は `/settings` 画面からも編集できる**（🆕 P20）。画面からの保存は `.env` への永続化のみで、`Settings` は起動時に一度だけ読み込む frozen オブジェクトのため**実行中の backend / celery worker・beat には反映されない**。値を変えたら該当プロセスを再起動すること。設定画面は §6 の認証機構と同じ前提（無認証・単一ユーザー・デスクトップ常駐）を引き継ぐため、同一 LAN 上の他端末からもキーを書き換えられる状態である点に留意する。

---

## 3. 監視・ヘルスチェック

| エンドポイント | チェック内容 | 用途 |
|---|---|---|
| `GET /api/health` | プロセスが生きているかのみ | liveness probe |
| `GET /health` | DB + Redis へ実接続（並行実行、各2秒タイムアウト） | readiness probe |

DB/Redis が落ちてもバックエンド自体は起動したまま応答し続けうるため、`/api/health` だけでは自走機能の実質停止を検知できない。`/health` を watch すること。

---

## 4. 障害対応

### 4.1 AI 銘柄ピックが生成されない / ポートフォリオ判定・通知が来ない / EOD レビューが出ない

**前提確認**: これらはすべて celery-beat 起動が前提（§1）。ワーカーのみでは自走しない。

| 症状 | 主な原因候補 | 対応 |
|---|---|---|
| 朝になってもピックが無い | Redis 停止 / beat 未起動 | `celery -A backend.celery_app inspect scheduled` でスケジュール登録を確認。`/health` で `redis: "ok"` か確認 |
| `ANTHROPIC_API_KEY` 未設定 | 該当機能が `not_configured`（ピック）または定量集計のみ（ポートフォリオ判定・EOD レビュー）で正常終了する仕様 | キーを設定してプロセス再起動。設定後は `POST /api/picks/run` 等で動作確認 |
| ポートフォリオ判定が場中なのに出ない | `_is_market_hours_jst()` のゲート（平日 9:00–15:30 JST）に該当していない、または保有銘柄が0件 | `GET /api/portfolio` で保有件数を確認。手動実行は `POST /api/portfolio/signals/run` |
| 通知が来ない | 判定の `action` が `hold`（変化なし）のみだった（正常。`hold` は通知しない設計） | 対応不要 |
| Web Push が届かない（アプリ内通知は表示される） | `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` 未設定、またはブラウザ側で購読が有効化されていない | `.env` に VAPID 鍵を設定 + 通知センターの「Push 通知を有効化」ボタンを押す |
| 昇格が全く提案されない | ホールドアウト・ペーパー成績のいずれかが champion を超えていない（正常、CLAUDE.md の昇格条件は AND） | `GET /api/registry/promotions` で判定履歴の `verdict`/`rationale` を確認 |

### 4.2 データベース（SQLite）に接続できない

**症状**: `/health` が `checks.db: "error"` で 503。

DB ファイル（`data/alpha_forge.db`）の存在・パーミッション・ディスク容量を確認する。ファイルが破損していなければ通常はプロセス再起動で復旧する。破損している場合は §5 のバックアップからリストアする。

### 4.3 Redis / Celery が落ちている

**症状**: `/health` が `checks.redis: "error"` で 503。

Redis プロセスの生死を確認し、落ちていれば再起動 → Celery ワーカー・beat も再起動する（ブローカー接続が切れたまま復旧しないことがあるため）。Redis が落ちていても閲覧系 API（ピック一覧・ポートフォリオ・モデルラボの各種グラフ等）は正常に動作し続ける。

### 4.4 J-Quants / yfinance が応答しない

**症状**: 株価・ファンダメンタル取得系が遅い、または `503`（サーキットブレーカ OPEN）。

**正常なフェイルセーフ動作**（`services/circuit_breaker.py`）。5回連続失敗で30秒 OPEN、以降は即座に 503。30秒後に自動で1回だけ試行を許可（HALF_OPEN）し、成功すれば復帰する。基本的に何もせず待つ。

### 4.5 ピック生成が数分以上かかる・全銘柄でナレッジ検索が失敗する

**症状**: `run_picks_task`/`POST /api/picks/run` が通常より大幅に遅い、または全銘柄で `related_notes` が空になる。

**主因**: kb_creator ベクトル検索API（ポート8077、別リポジトリ `obsidian-knowledge-base-creator` が提供）が未起動で、`services/vault/knowledge_search_client.py` が全銘柄で接続失敗・タイムアウト（`KB_SEARCH_TIMEOUT_SECONDS` 既定30秒）を繰り返すため（2026-09-14 に実際発生、CLAUDE.md「ローカル起動」参照）。`curl http://localhost:8077/health` で疎通確認し、未起動なら `tasks/start_vector_api.ps1` 等で起動する。

---

## 5. バックアップ・リストア

Alpha Forge には自動バックアップスクリプトはまだ無い。SQLite ファイル1本（`data/alpha_forge.db`）が唯一の永続状態のため、最低限以下を手動で行う。

```bash
# バックアップ（稼働中でも sqlite3 の online backup API を使えば安全だが、
# 最も簡単なのはプロセスを止めてからの単純コピー）
cp data/alpha_forge.db "data/alpha_forge_$(date +%Y%m%d_%H%M%S).db"
```

**リストア**: バックエンド・Celery を停止 → 現行 DB を退避 → 復元ファイルで置き換え → 起動して `/health` の `db: "ok"` を確認する。

定期バックアップの自動化（タスクスケジューラ / cron 登録）は今後の課題（§6）。

---

## 5b. 過去日リプレイ学習（🆕 P37）

モデルラボ「詳細」タブの「過去データでの再現学習（リプレイ）」から開始・停止・再開する
（API: `POST /api/replay/runs` 等）。実行は backend・celery worker とは独立した子プロセス
（`python -m backend.services.replay --run-id <uuid>`）で進み、進捗は `replay_runs` に残る。

- 初回は J-Quants から日付ごとの全銘柄日足を取得して `data/replay/bars/` にキャッシュする（約 1,300 日分・数分〜十数分）。2 回目以降は差分だけ取得する
- 子プロセスのログ: `data/replay/logs/<run_id>.log`
- 結果は本番台帳と別の `replay_*` テーブル。ダッシュボードの実測勝率・昇格判定のペーパー成績には影響しない
- 最後に学び直したプールモデルは `ml_pool` の challenger として登録されるだけで、本番採用は「モデルバージョン比較」の人手承認のみ
- backend 再起動やクラッシュで止まった場合（ハートビートが 15 分途絶えると停止扱い）は「続きから再開」で最後に完了した日の翌営業日から続く

## 6. 既知の制限・今後の課題

- 自動バックアップスクリプトは未整備（§5参照）。起動/停止スクリプト（`scripts/start.ps1`/`stop.ps1`、ログオン時自動起動の`scripts/register-startup-task.ps1`）は🔧2026-09-13に整備済み（§1参照、本節はその前の記述が残っていたもの）
- 認証機構は `Settings` の設定スロットのみが残っており、実際のログイン機能は無い（CLAUDE.md: デスクトップ常駐・単一ユーザー前提のため意図的に未実装）
- celery-beat の自走スケジュールのうち `run_picks_task`・`run_portfolio_monitor_task` は🔧2026-09-20に日本の祝日を考慮するよう修正済み（`jpholiday`、§1参照）。それ以外のタスクは引き続き祝日を考慮しない
- Web Push はブラウザの購読が有効な場合のみ配信される。デスクトップ常駐前提のため PWA 化・インストール導線は意図的に作っていない
- 通知はアプリ内表示 + Web Push のみ（メール/Slack/LINE 等の外部連携は無し）

---

## 参照ドキュメント

- `plans/02_アーキテクチャ.md` — レイヤー構成・技術スタックの選定理由
- `plans/03_システム設計.md` — テーブル設計・API 設計・フェーズ別の詳細設計
- `plans/04_タスクリスト.md` — フェーズごとの実装内容・移植可否判断・スコープ決定の記録
- `plans/05_決定ログと未決事項.md` — プロジェクト全体の決定ログ
- `CLAUDE.md` — プロジェクト固有のコーディング規約・ドメインルール
