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
  celery_app.py      Celery 設定（beat スケジュールは枠のみ）
  alembic/           マイグレーション（0001_baseline に全ドメインテーブル）
  routers/           HTTP / WS エンドポイント
  services/          ドメインロジック（フェーズごとに Market Lens から移植）
frontend/
  src/app/           dashboard / stock-detail / portfolio / model-lab / notifications
  src/components/ui/  DataTable ほか共通部品
  src/lib/           API クライアント / SSE・WS クライアント
  src/middleware.ts  nonce ベース CSP
plans/               PRD / アーキテクチャ / システム設計 / タスクリスト / 決定ログ
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

# frontend（ポート 3001）
cd frontend; npm run dev
```

Redis は別途起動が必要です（`docker run -p 6379:6379 redis` 等）。

## ローカル CI（push 前に全通し）

```powershell
# backend
.venv/Scripts/python.exe -m ruff check backend
.venv/Scripts/python.exe -m black --check backend
.venv/Scripts/python.exe -m mypy backend
.venv/Scripts/python.exe -m bandit -r backend --exclude backend/tests,backend/alembic
.venv/Scripts/python.exe -m pytest backend/tests -q

# frontend
cd frontend
npx tsc --noEmit
npx eslint .
npx jest
npx next build
```

## 開発フェーズ

`plans/04_タスクリスト.md` の P0〜P8。現在は **P1（基盤）** まで完了。
