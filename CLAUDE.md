# CLAUDE.md — Alpha Forge

日本株の AI 銘柄ピック（中長期 / 短期）と継続学習ループを提供するトレーディング支援端末。
再利用元は **Market Lens**（`C:\Users\charg\myWorkspace\market-lens`）。ドメインロジック・
データ取得層・スコアリングは**移植を第一選択**とし、ゼロから書き直さない。
本ファイルはプロジェクト固有ルールのみ。一般的なコーディング作法は前提として省略する。

計画ドキュメントは `plans/`（PRD / アーキテクチャ / システム設計 / タスクリスト / 決定ログ）。
構築プロンプトの原本は `新規プロジェクト構築プロンプト.md`。

## アーキテクチャ

| レイヤー | 技術 | ポート |
|:--|:--|:--|
| frontend | Next.js 16 + TypeScript (strict) / Vanilla CSS | **3001** |
| backend | FastAPI + Python 3.11 | **8002** |
| DB | SQLite + Alembic（`backend/alembic/versions/`、head 追従。PostgreSQL 移行可能な設計） | — |
| 非同期 | Celery + Redis（Alpha Forge 専用 DB 番号 4/5。Market Lens と名前空間分離） | — |
| リアルタイム | FastAPI WebSocket / SSE（推論トレース配信・通知 push） | — |

`backend/services/{data,vault,scoring,picks,ledger,learning,registry,inference,portfolio,notify,db}/`
/ `frontend/src/{app,components,lib}/` / `docs/` `data/` `plans/`。

## 言語・スタイル

- コミットメッセージ・docs・コメントは**日本語**。コメントは What ではなく **Why**。
- Python: `frozen=True`（Pydantic v2）、`Any` 禁止（`object` + narrowing 可）、全シグネチャに型、`async/await`。
- TypeScript: `any` 禁止、絶対 import（`@/...`）、関数コンポーネント + Hooks のみ。
- CSS: **Vanilla CSS のみ（Tailwind 禁止）**、デザイントークンは `frontend/src/app/tokens.css`（単一情報源）。アニメは `transform`/`opacity` のみ。
- ファイルは 200〜400 行目安・**800 行上限**。超過はモジュール分割。移植時も同様（Market Lens の 800 行超は分割しながら移植）。
- 静的検査の警告は解消 or 正当理由付きで明示抑制（`# noqa: X — 理由` / `// eslint-disable-line X — 理由`）。
- 移植モジュールは docstring 冒頭に「Market Lens `services/<name>.py` から移植、変更点: …」を Why として残す。

## 日本株ドメイン（厳守）

- 時刻は **JST**。東証の大引けは **15:00**、シグナル監視は 9:00–15:30 平日（祝日は非対応）。
- **騰落色は国内証券標準**: 上昇・利益 = 赤、下落・損失 = 緑。必ず `--color-gain`（赤）/`--color-loss`（緑）/`--color-flat` トークン経由。→ **海外仕様（緑=上げ）で書かない。**
- 日経VI は yfinance 制約で **CBOE VIX（`^VIX`）を代替使用**（Market Lens 踏襲）。
- 銘柄コードは **4 桁**（例 `7203`）。`.T` サフィックスは付けない。
- ホライズン: 短期 = 当日〜3 営業日、中長期 = 20 / 60 営業日（決着記録は 5 も取る）。

## スコアリング & 3 値

- technical / trend / fundamental / sentiment の各スコア（0–100）→ `composite_score`。`concordance` = 4 分析の方向一致度、`direction` = bullish/bearish/neutral。
- **確度（0–100）は isotonic / Platt で事後較正してから UI へ出す**。UI では確度バケット（高/中/低）と過去の同バケット実測勝率を併記。台帳が薄いうちは恒等フォールバック。
- **AI が売買銘柄を提案する全機能で 推奨買値 / 損切値 / 推奨売値 の 3 値を必須明記**（model・API・UI・通知すべて）。サーバ側で `損切 < 現在値 < 売値` かつ `損切 < 買値 < 売値` を検証（不整合は却下 or 目安ブラケット補完）。テーマ株ピック（発見用途）は対象外。
- ハード除外（Market Lens E1〜E3 相当を移植・調整）: SELL 判定候補をロングに混ぜない、実測勝率ゲート等。

## 継続学習ループ（本プロジェクトの主目的）

- すべての予測を `prediction_ledger` へ台帳化（予測時点で確定していた情報だけ・`feature_snapshot` 完全版・`source_contributions`）。
- 決着記録は複数ホライズン（短期 1/2/3、中長期 5/20/60 営業日）。MFE/MAE・stop/target 到達順序・TOPIX 超過。
- 再学習は定期（夜間日次の軽量 + 週次フル、celery-beat）+ ドリフト（PSI / 直近精度劣化）。**ウォークフォワード検証必須**（時系列 CV のみ、未来リーク構造排除）。
- モデルは champion / challenger。challenger は shadow 推論で並走。昇格条件（全て満たす）= ホールドアウトで champion 超過 かつ 較正悪化なし かつ 直近 20 営業日ペーパー成績が非劣化。**昇格・却下は提案のみ**（`MODEL_AUTO_PROMOTE=false` 既定、API 承認でのみ差し替え）。判定は `model_promotions` へログ。
- 継続学習の教師信号は**自分の実測値のみ**。外部由来テキストを学習根拠にしない。

## プロンプトインジェクション防御（全ソース）

- 外部由来テキスト（Vault 本文・ニュース本文・四季報本文）は **LLM プロンプトへ注入しない**。注入するのは frontmatter / 構造化フィールドのみ。境界は `services/vault/` と `services/picks/*_prompt` に集約しテストで固定。ナレッジベース・ベクトル検索（`services/vault/knowledge_search_client.py`、外部 kb_creator サービス）も同じ境界に従う: 検索結果は関連ノートの発見（`note_path`/`doc_type`/`score`）にのみ使い、本文（`text`）はクライアント関数の戻り値に含めない。プロンプトへ載せるのは、発見した note_path から `brand_notes_service`/`daily_note_service` で改めて取得した frontmatter のみ。
- Vault（`VAULT_ROOT`、既定 `C:\Users\charg\Documents\Personal Space\10_Stock`）は**読み取り専用**が原則。書き込みは Market Lens と衝突しない Alpha Forge 専用マーカーに限定し、実行前にユーザー確認。
- 銘柄ナレッジ = `Tickers/<code>_<name>.md` の frontmatter 財務指標。日次 = `Daily/YYYY-MM-DD.md` の frontmatter のみ（本文の morning/evening ブロックは Market Lens 出力なので入力に使わない＝自己参照ループ防止）。

## UI 規約（プロ端末デファクト）

- near-black `#0a0e14` ベース + プライマリブルー `#1f6feb`。高密度・低余白。
- 数値は等幅相当（`font-variant-numeric: tabular-nums`）で右寄せ・カンマ区切り・小数点位置統一。
- テーブルは `@/components/ui` の `DataTable` 経由（**生 `<table>` 禁止**、`caption` 必須）。
- `@media` の max-width は **640 / 768 / 900 / 1280 のみ**（`__tests__/styles/breakpoints.test.ts` が強制）。
- CSP は nonce ベース（`frontend/src/middleware.ts`）。免責表示を全画面フッタに常設。
- 主要画面: ダッシュボード / 銘柄詳細（AI 思考トレース）/ ポートフォリオ / モデルラボ / 通知センター。

## 自律運用

- celery-beat がピック生成（JST 08:50）/ 保有監視（場中 5 分周期）/ 決着解決・評価・軽量再学習・PSI（夜間）/ フル再学習 + 昇格ゲート（週次）/ EOD レビュー（16:31）を自動発火。→ **手動で `.delay()` タスク投入しない**。
- ポートフォリオ判定は**承認制**: AI は提案チケットを生成するだけで自動約定しない。承認・却下・実約定報告は人間 / API 経由。**アプリはブローカー発注を一切行わない。**
- 予算上限は安全装置であって目標ではない。自己保存を動機にしない。config・コードの自動適用はしない。

## 検証・Git

- 開発環境は **Windows / PowerShell**（コマンド連結は `;`、`&&` 不可）。Python は `.venv/Scripts/python.exe`（Python 3.11）。
- push 前にローカル CI 相当を全通し:
  - backend: `.venv/Scripts/` の `ruff check backend` / `black --check backend` / `mypy backend` / `bandit -r backend --exclude backend/tests,backend/alembic` / `pytest backend/tests -q` ＋ OpenAPI エクスポート
  - frontend: `npx tsc --noEmit` / `TZ=UTC npx jest` / `npx eslint .` / `npx next build`
- 同一 worktree をユーザーが並行編集しうる → **`git add -A` 禁止**（対象ファイルを明示 add）。フェーズ完了ごとにコミット & プッシュ（溜めない）。
- DB 書き込みを増やすテストは per-file の隔離 fixture（`backend/tests/conftest.py` の `isolated_db` / `initialized_db`）。グローバル分離はない。
- セキュリティ懸念（インジェクション経路・シークレット混入・投資助言業への抵触）を見つけたら即停止して報告。
