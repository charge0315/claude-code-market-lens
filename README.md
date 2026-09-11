# Alpha Forge

日本株（東証、銘柄コード 4 桁）の **AI 銘柄ピック**（中長期 / 短期）と、
予測を台帳化して決着結果から学習し直す **継続学習ループ**、
そして推論パイプラインを端末上でライブに見せる **AI 思考の可視化** を提供する
トレーディング支援端末です。

> 本アプリの出力は分析結果・参考情報であり、投資助言ではありません。
> **ブローカーへの発注は一切行いません。** 約定は利用者が手動で行います。

再利用元は [Market Lens](../market-lens)。ドメインロジック・データ取得層・スコアリングは
移植を第一選択としています。詳細は [`plans/`](plans/) を参照。

## 構成

| レイヤー | 技術 | ポート |
|:--|:--|:--|
| frontend | Next.js 16 + TypeScript (strict) / Vanilla CSS | 3001 |
| backend | FastAPI + Python 3.11 | 8002 |
| DB | SQLite + Alembic | — |
| 非同期 | Celery + Redis（DB 番号 4 / 5） | — |

```
backend/
  main.py            FastAPI アプリ（/health, /api/health）
  config.py          env 一元（起動時 fail-fast）
  celery_app.py      Celery 設定（beat スケジュール一元、_BEAT_SCHEDULE 参照）
  alembic/           マイグレーション（0001_baseline に全ドメインテーブル）
  routers/           HTTP / WS エンドポイント
  services/          ドメインロジック（フェーズごとに Market Lens から移植 / 新規設計）
frontend/
  src/app/           dashboard / stock-detail / portfolio / model-lab / notifications
  src/components/     ui / layout / pipeline / dashboard / portfolio / notify / model-lab / stock-detail
  src/lib/           API クライアント / SSE・WS クライアント / push（Web Push）
  src/middleware.ts  nonce ベース CSP
  e2e/               Playwright E2E テスト
plans/               PRD / アーキテクチャ / システム設計 / タスクリスト / 決定ログ
docs/                as-built アーキテクチャ概観・運用 Runbook・OpenAPI
```

## セットアップ（Windows / PowerShell）

```powershell
# 1. 環境変数
Copy-Item .env.example .env
# .env の ML_SECRET_KEY（32文字以上）と ML_PASSWORD_HASH（bcrypt）を埋める

# 2. backend（Python 3.11）
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r backend/requirements-ci.txt
.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head

# 3. frontend
cd frontend; npm ci; cd ..
```

## 起動

```powershell
# backend（ポート 8002）
.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8002 --reload

# Celery worker（別ターミナル。Windows は --pool=solo）
.venv/Scripts/celery.exe -A backend.celery_app worker --pool=solo --loglevel=info

# Celery beat（別ターミナル。ピック生成・保有監視・EOD レビュー等の自走スケジュール。
# Windows は worker への埋め込み起動 -B を拒否するため必ず別プロセス）
.venv/Scripts/celery.exe -A backend.celery_app beat --loglevel=info

# frontend（ポート 3001）
cd frontend; npm run dev
```

Redis は別途起動が必要です（`docker run -p 6379:6379 redis` 等）。自走スケジュールの詳細・障害対応は [`docs/operations.md`](docs/operations.md) を参照。

## ローカル CI（push 前に全通し）

```powershell
# backend
.venv/Scripts/python.exe -m ruff check backend
.venv/Scripts/python.exe -m black --check backend
.venv/Scripts/python.exe -m mypy backend
.venv/Scripts/python.exe -m bandit -r backend --exclude backend/tests,backend/alembic
.venv/Scripts/python.exe -m pytest backend/tests -q
.venv/Scripts/python.exe scripts/export_openapi.py

# frontend
cd frontend
npx tsc --noEmit
npx eslint .
npx jest --coverage
npx next build
npx playwright test   # backend を先に起動しておくこと
```

## 開発フェーズ

`plans/04_タスクリスト.md` の P0〜P8。**全フェーズ完了**（AI 銘柄ピック / 継続学習ループ /
AI 思考の可視化 / ポートフォリオ承認キュー / 通知 / モデルラボ）。詳細な as-built
アーキテクチャは [`docs/architecture.md`](docs/architecture.md)、運用は
[`docs/operations.md`](docs/operations.md) を参照。
