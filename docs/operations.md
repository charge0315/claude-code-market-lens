# 運用Runbook

本ドキュメントは Alpha Forge を実際に動かし続ける（起動・監視・障害対応・バックアップ）ための手順書です。設計判断の背景は `plans/02_アーキテクチャ.md` `plans/03_システム設計.md` を、フェーズごとの実装詳細・移植可否判断は `plans/04_タスクリスト.md` を参照してください。ここでは「今すぐ何をすればよいか」に絞って記述します。

対象読者: 本システムを自宅PC等で動かし続ける開発者本人（デスクトップ常駐・シングルユーザー構成が前提。CLAUDE.md 参照）。

---

## 1. 起動・停止

Market Lens と異なり、Alpha Forge は起動をまとめるスクリプト（`start.ps1` 相当）を持たない。以下 4 プロセスを手動で起動する。

```powershell
# 1. バックエンド（ポート 8002）
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002

# 2. Celery ワーカー（ピック生成・保有監視・学習バッチ・通知・EOD レビュー等の実処理。
#    Windows は --pool=solo 必須）
.venv\Scripts\celery.exe -A backend.celery_app worker --pool=solo --loglevel=info

# 3. Celery beat（定期実行スケジューラ。ワーカーとは別プロセス — Windows は
#    `worker -B`（beat 埋め込み）を拒否するため必ず分離する、Market Lens と同じ制約）
.venv\Scripts\celery.exe -A backend.celery_app beat --loglevel=info

# 4. フロントエンド（ポート 3001）
cd frontend && npm run build && npm start   # 本番相当
# cd frontend && npm run dev                 # 開発時
```

Redis はローカルで別途起動しておく（`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` の既定は `redis://127.0.0.1:6379/4` `/5` — Market Lens の `/0` `/1` と衝突しないよう DB 番号を分離済み）。**Redis 未起動でもバックエンド自体は起動する**が、celery-beat 経由の自走機能（下記表）はすべて動かない。

停止は各プロセスを `Ctrl+C`。Celery ワーカーは実行中タスクの完了を待たず即終了する（再実行すればよい、DB は壊れない）。

### 起動確認

```bash
curl http://localhost:8002/api/health   # liveness: プロセスが生きているか
curl http://localhost:8002/health        # readiness: DB/Redis まで含めた疎通確認
```

### 自走スケジュール（celery-beat、`backend/celery_app.py` の `_BEAT_SCHEDULE` が単一情報源）

時刻はすべて JST。beat の内部設定は UTC 固定のため、コード上は UTC 換算値で書かれている点に注意（本表はすでに JST 換算済み）。

| 時刻 / 周期 | タスク | 内容 |
|---|---|---|
| 平日 08:50 | `run_picks_task("mid_term")` | 中長期ピック生成 |
| 平日 08:52 | `run_picks_task("short_term")` | 短期ピック生成（2分ずらして直列ワーカーの二重占有回避） |
| 毎日 16:38 | `resolve_pick_outcomes_task` | 未決着ピックの決着解決（複数ホライズン） |
| 毎日 16:48 | `update_eval_metrics_task` | 評価指標（較正・IC・成績）再集計 |
| 毎日 07:13/10:13/13:13/16:13 | `sync_trends_task` | Trend Tracking Agent 同期（TTL 3h） |
| 毎日 16:31 | `run_eod_review_task` | 大引け後レビュー生成（`portfolio_signals` 当日分の集計 + LLM 教訓抽出） |
| 場中5分おき（平日 9:00–15:30、内部ゲート） | `run_portfolio_monitor_task` | 保有銘柄の AI 売買タイミング判定（HITL 提案のみ、自動約定なし） |
| 常時5分おき | — | *(枠のみ。P5 以降で個別タスクを追加した箇所は上記に統合済み)* |
| 日曜 03:30 | `run_drift_check_task` | 特徴量分布ドリフト（PSI）週次計測 |
| 日曜 03:45 | `run_promotion_evaluation_task` | challenger 昇格判定（週次、提案のみ・自動昇格なし） |
| 毎月1日 04:00 | `run_pool_training_task` | 断面プール分類器（`lane="ml_pool"`）の月次再学習 |

祝日は非対応（`plans/01_PRD` で確認済みの既定スコープ）。休場日にも保有監視タスクは5分おきに起動されるが、内部で無害な早期 return をする。

**手で `.delay()` タスクを投入しない**（CLAUDE.md）。手動実行が必要な場合は対応する API（`POST /api/picks/run`、`POST /api/portfolio/signals/run`、`POST /api/portfolio/eod-review/run`、`POST /api/eval/run`、`POST /api/registry/promotions/evaluate` 等）を使う。

---

## 2. 環境変数

`.env.example` をコピーして `.env` を作成する（Git 管理外）。

| 変数 | 必須 | 既定値 | 用途 |
|---|:---:|---|---|
| `ML_SECRET_KEY` | ✅ | なし（16文字未満は起動時エラー） | Market Lens の認証基盤を踏襲した設定スロット。Alpha Forge は未認証（単一ユーザー・デスクトップ常駐前提、CLAUDE.md）だが `Settings()` の fail-fast 検証は残しているため値の設定自体は必須 |
| `ML_PASSWORD_HASH` | ✅ | なし（空は起動時エラー） | 同上（現状ログイン機能では未使用。上記と同じ理由で必須） |
| `ML_USERNAME` | – | `admin` | 同上（未使用） |
| `BACKEND_PORT` / `FRONTEND_PORT` | – | `8002` / `3001` | Market Lens（8001/3000）と非衝突のポート |
| `ML_CORS_ORIGINS` | – | `http://localhost:3001,http://127.0.0.1:3001` | CORS 許可オリジン |
| `BACKEND_PROXY_TARGET` | – | `http://127.0.0.1:8002` | frontend の `/api` `/ws` リライト先（Next.js サーバのみ参照） |
| `ML_COOKIE_SECURE` | – | `false` | 本番 https では `true` 必須 |
| `JQUANTS_API_KEY` | – | 空（yfinance にフォールバック） | J-Quants API キー |
| `ANTHROPIC_API_KEY` | – | 空（AI 機能が `not_configured` を返す） | Claude API キー（ピック生成・ポートフォリオ判定・EOD レビューの LLM 深掘りに使用） |
| `ANTHROPIC_MODEL` | – | `claude-sonnet-5` | 使用する Claude モデル ID |
| `LLM_DAILY_COST_LIMIT_USD` | – | `5.0` | LLM コストの安全装置（目標ではない、CLAUDE.md）。超過時の挙動は `services/api_cost` 参照 |
| `DATABASE_URL` | – | `sqlite+aiosqlite:///./data/alpha_forge.db` | DB 接続先（PostgreSQL 移行可能な設計） |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | – | `redis://127.0.0.1:6379/4` `/5` | Celery（Market Lens と DB 番号分離） |
| `VAULT_ROOT` | – | `Personal Space/10_Stock` | Obsidian Vault ルート（読み取り専用が原則） |
| `BRAND_NOTES_DIR` / `DAILY_NOTES_DIR` | – | 空（`VAULT_ROOT` から導出） | 銘柄ナレッジ / 日次マーケットノートのディレクトリ |
| `SHIKIHO_ENABLED` | – | `false` | 四季報連携（当面スタブ） |
| `MODEL_AUTO_PROMOTE` | – | `false` | **常に false 運用**。昇格は `POST /api/registry/promotions/{id}/apply` の人手承認でのみ行う |
| `PAPER_MIN_DAYS` | – | `20` | champion 昇格ゲートの最小ペーパー成績日数 |
| `DRIFT_PSI_THRESHOLD` | – | `0.2` | PSI ドリフト警告閾値 |
| `CALIBRATION_METHOD` | – | `auto` | 確度較正方式（`auto`/`isotonic`/`platt`/`identity`） |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | – | 空（Push 配信は無効、アプリ内通知のみ） | Web Push 用 VAPID 鍵。`npx web-push generate-vapid-keys` で生成 |

必須変数（`ML_SECRET_KEY`, `ML_PASSWORD_HASH`）はどちらか欠けると `backend/config.py` の `Settings()` が起動時に例外を投げる（フェイルファスト設計、Market Lens 踏襲）。ローカル動作確認だけであれば任意のダミー値（32文字以上の `ML_SECRET_KEY` と bcrypt 形式の `ML_PASSWORD_HASH`）で起動できる。

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

**正常なフェイルセーフ動作**（`services/circuit_breaker.py`、Market Lens 踏襲）。5回連続失敗で30秒 OPEN、以降は即座に 503。30秒後に自動で1回だけ試行を許可（HALF_OPEN）し、成功すれば復帰する。基本的に何もせず待つ。

---

## 5. バックアップ・リストア

Alpha Forge には Market Lens のような自動バックアップスクリプトはまだ無い。SQLite ファイル1本（`data/alpha_forge.db`）が唯一の永続状態のため、最低限以下を手動で行う。

```bash
# バックアップ（稼働中でも sqlite3 の online backup API を使えば安全だが、
# 最も簡単なのはプロセスを止めてからの単純コピー）
cp data/alpha_forge.db "data/alpha_forge_$(date +%Y%m%d_%H%M%S).db"
```

**リストア**: バックエンド・Celery を停止 → 現行 DB を退避 → 復元ファイルで置き換え → 起動して `/health` の `db: "ok"` を確認する。

定期バックアップの自動化（タスクスケジューラ / cron 登録）は今後の課題（§6）。

---

## 6. 既知の制限・今後の課題

- 自動バックアップスクリプト・起動/停止スクリプト（`start.ps1`/`stop.ps1` 相当）は未整備。単一プロセスずつ手動起動する運用が前提
- 認証機構は Market Lens から `Settings` のスロットのみ引き継いでおり、実際のログイン機能は無い（CLAUDE.md: デスクトップ常駐・単一ユーザー前提のため意図的に未実装）
- celery-beat の自走スケジュールは日本の祝日を考慮しない（`trading_calendar.py` と同じスコープ外の判断）
- Web Push はブラウザの購読が有効な場合のみ配信される。デスクトップ常駐前提のため PWA 化・インストール導線は意図的に作っていない
- 通知はアプリ内表示 + Web Push のみ（メール/Slack/LINE 等の外部連携は無し）

---

## 参照ドキュメント

- `plans/02_アーキテクチャ.md` — レイヤー構成・技術スタックの選定理由
- `plans/03_システム設計.md` — テーブル設計・API 設計・フェーズ別の詳細設計
- `plans/04_タスクリスト.md` — フェーズごとの実装内容・移植可否判断・スコープ決定の記録
- `plans/05_決定ログと未決事項.md` — プロジェクト全体の決定ログ
- `CLAUDE.md` — プロジェクト固有のコーディング規約・ドメインルール
