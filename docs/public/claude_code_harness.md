# Claude Code ハーネス仕様書（公開用サンプル）

> **これは何か**
> 本プロジェクトの開発・運用に Claude Code をどう「ハーネス」として組み込んでいるかをまとめた
> スナップショットです。実体は 2 層構成になっています。
>
> 1. **グローバル層**（`~/.claude/CLAUDE.md` + `~/.claude/rules/**`） — 全プロジェクト共通の運用ポリシー。
>    言語規約、自律動作の可否境界、エージェント使い分け、コーディング規約、テスト・セキュリティ基準、
>    フックの運用方針など。ローカル環境の個人設定なのでこのリポジトリには含まれません。
> 2. **プロジェクト層**（このリポジトリの `CLAUDE.md`） — 本プロジェクト固有のドメイン知識・
>    アーキテクチャ・自律運用の実装詳細。
>
> このファイルは、外部の読者が「Claude Code をどう設定してこのプロジェクトを開発・運用しているか」を
> 把握できるよう、両層の要点を公開用に統合し、個人のローカルパスやメールアドレスのみダミー値へ
> 置き換えたものです。API キー等の機密値はもともとどの設定ファイルにも直書きされていません
> （すべて `.env` 経由、`.env` 自体は非コミット）。**グローバル層は本リポジトリの一部ではなく、
> 内容は時間とともに変わりうる点に注意してください（あくまで本ドキュメント作成時点のスナップショット）。**

---

## 1. 全体像

```
~/.claude/CLAUDE.md            … 全プロジェクト共通の方針（言語・自律動作・参照先ナレッジベース）
~/.claude/rules/common/*.md    … 言語非依存の共通規約（agents / code-review / coding-style /
                                   development-workflow / git-workflow / hooks / patterns /
                                   performance / security / testing）
~/.claude/rules/web/*.md       … Web フロントエンド固有規約（common/* を継承・拡張）
~/.claude/settings.json        … フック（PreToolUse / PostToolUse / Stop 等）・権限設定
~/.claude/agents/*.md          … サブエージェント定義（planner / code-reviewer 等）
~/.claude/projects/<repo>/memory/  … リポジトリ横断で永続化される「記憶」（後述 §6）

<repo>/CLAUDE.md               … このプロジェクト固有の運用ルール（本ドキュメントの元）
<repo>/.claude/launch.json     … frontend/backend の起動設定（ポート等）
<repo>/新規プロジェクト構築プロンプト.md
                                … このプロジェクトをゼロから構築させた原本プロンプト
                                   （公開版: docs/public/project_construction_prompt.md）
<repo>/docs/operations.md      … 運用 Runbook（起動手順・障害対応・env 変数一覧）
<repo>/plans/                  … 凍結された計画成果物（PRD / アーキテクチャ / タスクリスト）
```

Claude Code は起動時に上記 2 層の `CLAUDE.md` と該当する `rules/*.md` をすべて読み込み、
プロジェクト固有ルールがグローバルルールを上書き・補完する形で動作します。

---

## 2. グローバル運用ポリシー（全プロジェクト共通）

### 2.1 自律動作の方針

| 分類 | 扱い |
|:--|:--|
| **確認なしで自走してよい** | コード編集、テスト作成・実行、リンタ/型チェック、ローカル検証、リポジトリ内の調査 |
| **確認または明示指示が必要** | コミット / push / PR 作成 / ブランチのマージ、外部サービスへの送信・公開、不可逆操作（削除・上書き）、認証情報・資格情報の入力、設定/権限の恒常変更 |

承認済みの範囲は勝手に広げない。あるコンテキストでの承認を別の操作へ流用しない。

### 2.2 開発ワークフロー（Feature Implementation Workflow）

```
0. 調査・再利用調査（新規実装前に必須）
   - 既存実装・テンプレートを GitHub / パッケージレジストリで先に探す
   - 一次情報（公式ドキュメント）を確認してから実装
   - 80% 以上要件を満たすオープンソース実装があれば移植・ラップを優先し、ゼロから書かない
1. 計画（planner エージェント）— PRD / アーキテクチャ / システム設計 / タスクリストを事前生成
2. TDD（tdd-guide エージェント）— RED → GREEN → REFACTOR、カバレッジ 80% 以上
3. コードレビュー（code-reviewer / security-reviewer エージェント）
   — CRITICAL / HIGH は必ず修正してからコミット
4. コミット & プッシュ（規約は §2.4）
5. プッシュ前チェック — CI 相当をローカルで全通し、マージコンフリクト解消、ブランチ最新化
```

### 2.3 サブエージェントの使い分け

| エージェント | 用途 |
|:--|:--|
| planner | 複雑な機能・リファクタリングの実装計画 |
| architect | アーキテクチャ上の意思決定 |
| tdd-guide | 新機能・バグ修正のテストファースト実装 |
| code-reviewer | コード品質・パターン・ベストプラクティスのレビュー |
| security-reviewer | 認証・入力処理・DB・外部 API・決済等のセキュリティレビュー |
| build-error-resolver | ビルド失敗時の修正 |
| e2e-runner | クリティカルユーザーフローの E2E テスト |
| refactor-cleaner | デッドコードの除去 |
| doc-updater | ドキュメント更新 |

複雑な問題には役割分担した並列サブエージェント（事実確認役・シニアエンジニア役・セキュリティ役・
一貫性レビュー役・重複検出役など）を使う「マルチパースペクティブ分析」も併用する。

### 2.4 Git ワークフロー

- コミットメッセージ: `<type>: <説明>`（`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf` / `ci`）。
  本文・メッセージは日本語で記述。
- PR 作成時は最新コミットだけでなく `git diff <base>...HEAD` でブランチ全体の差分を確認してから
  サマリと Test Plan を書く。
- push 前にローカル CI 相当をすべて通す（§4.5）。

### 2.5 コーディングスタイル共通規約

- **イミュータビリティ**: 既存オブジェクトを破壊的変更せず、常に新しいオブジェクト/コピーを返す。
- **KISS / DRY / YAGNI**: 単純さを優先、本物の重複だけを抽象化、将来のための投機的な一般化はしない。
- ファイル構成は「多くの小さいファイル」を志向: 200〜400 行目安・800 行上限、機能/ドメイン単位でまとめる。
- エラーは境界（ユーザー入力・外部 API 応答）で必ず検証し、黙って握り潰さない。
- 命名: 変数/関数 `camelCase`、真偽値は `is`/`has`/`should`/`can` 接頭辞、型/コンポーネントは `PascalCase`、
  定数は `UPPER_SNAKE_CASE`。
- 早期リターンで深いネスト（4 段超）を避け、マジックナンバーは名前付き定数にする。
- コンパイラ/リンタの警告は解消するか、理由付きで明示的に抑制する（放置は失敗扱い）。

### 2.6 テスト規約

- 最低カバレッジ 80%。Unit / Integration / E2E をすべて用意する。
- TDD: テストを先に書き FAIL を確認 → 最小実装で PASS → リファクタ → カバレッジ確認。
- テスト構造は AAA（Arrange-Act-Assert）、テスト名は振る舞いを説明する記述的な名前にする。
- テスト失敗時はまず実装を疑う（テストが誤っている場合のみテストを直す）。

### 2.7 セキュリティ規約

- コミット前チェック: ハードコードされたシークレットがない / 入力検証 / SQLi・XSS・CSRF 対策 /
  認可検証 / レート制限 / エラーメッセージが機密情報を漏らさない、をすべて確認。
- シークレットは環境変数 or シークレットマネージャ経由のみ。ソースに直書きしない。
- 起動時に必須シークレットの存在を検証する。漏洩の疑いがあれば即ローテーション。
- セキュリティ懸念を発見したら **即停止 → security-reviewer で精査 → CRITICAL を先に修正 → 類似箇所を横展開確認**。

### 2.8 フックシステム

`~/.claude/settings.json` の `hooks` に、以下のようなイベント別フックを登録して自動化している
（内容は個人環境のローカルスクリプトを指すため非公開。カテゴリのみ示す）:

| イベント | 用途の例 |
|:--|:--|
| `PreToolUse`（Bash） | `--no-verify` 等の危険フラグ付き git コマンドをブロック、コミット品質チェック、push 前リマインド |
| `PreToolUse`（Write） | 大きすぎるファイル作成の警告 |
| `PostToolUse`（Write/Edit） | フォーマッタ・リンタ・型チェックの自動実行 |
| `Stop` | セッション終了時のビルド検証 |

Web フロントエンド向けには `pnpm prettier --write` / `pnpm eslint --fix` / `pnpm tsc --noEmit` /
`pnpm stylelint --fix` を編集直後に走らせ、`pnpm build` をセッション終了時の最終確認として使う構成を
推奨パターンとしている（プロジェクト側の実際のコマンドは §4.5 を参照）。

### 2.9 実行アクションの慎重さ

破壊的操作（削除・force push・`git reset --hard` 等）、共有状態に影響する操作（push・PR・外部通知）、
サードパーティサービスへのアップロードは、事前に文脈・アクション・影響範囲を提示してユーザーに確認する。
セッション内の一度の承認は「その範囲」にのみ有効で、別の操作への流用はしない。

---

## 3. プロジェクト固有ポリシー（このリポジトリの `CLAUDE.md`）

以下は本プロジェクト（日本株 AI 銘柄ピック & 継続学習トレーディング支援端末）に特化した追加ルールです。
汎用的な開発規約は §2 で共通化済みのため、ここにはドメイン・アーキテクチャ固有の内容のみ記載します。

### 3.1 アーキテクチャ

| レイヤー | 技術 | ポート |
|:--|:--|:--|
| frontend | Next.js + TypeScript (strict) / Vanilla CSS | 3001 |
| backend | FastAPI + Python 3.11 | 8002 |
| DB | SQLite + Alembic（PostgreSQL 移行可能な設計） | — |
| 非同期 | Celery + Redis（専用 DB 番号で名前空間分離） | — |
| リアルタイム | FastAPI WebSocket / SSE | — |

移植元プロジェクトが別途存在し、ドメインロジック・データ取得層・スコアリングは「移植を第一選択」とし
ゼロから書き直さない方針（詳細は `docs/public/project_construction_prompt.md` §5）。

### 3.2 日本株ドメインルール（厳守事項の例）

- 時刻はすべて JST。シグナル監視は平日 9:00–15:30、東証大引けは 15:00、祝日は `jpholiday` で判定して除外。
- **騰落色は国内証券標準**（上昇・利益 = 赤、下落・損失 = 緑）。海外仕様（緑 = 上げ）で書かない。
- 銘柄コードは 4 桁（`.T` サフィックスなし）。
- AI が売買銘柄を提案する全機能で **推奨買値 / 損切値 / 推奨売値の 3 値を必須明記**し、
  サーバ側で `損切 < 現在値 < 売値` かつ `損切 < 買値 < 売値` を検証する。

こうしたドメイン固有の制約を `CLAUDE.md` に明文化しておくことで、Claude Code が実装のたびに
「海外基準の配色を使ってしまう」「投資助言業に抵触する断定表現を書いてしまう」といった
ドメイン外の既定挙動に流れるのを防いでいる。

### 3.3 プロンプトインジェクション防御の境界

外部由来のテキスト（Vault ノート本文・ニュース本文・四季報本文など）を LLM プロンプトへ直接注入せず、
frontmatter や構造化フィールド（enum / 数値 / 検証済みコード）のみを転送する境界を、
データ取得層とプロンプト生成層の間に明示的に設けている。継続学習の教師信号も自分の実測値のみを使い、
外部由来テキストを学習根拠にしない。この境界はテストで固定し、新しい外部データソースを追加する際は
必ず同じ境界原則を適用するよう `CLAUDE.md` に明記している。

### 3.4 自律運用（celery-beat によるタスク自動化）

定期実行タスク（ピック生成・保有監視・決着解決・軽量/フル再学習・EOD レビュー等）は celery-beat で
自動発火させる。**ポートフォリオの実際の売買は常に承認制** — AI は提案チケットを生成するだけで、
自動約定・自動ブローカー発注は一切行わない。予算上限は安全装置であって目標ではなく、
自己保存を動機にした config・コードの自動適用はしない。

### 3.5 モデル昇格ゲート

continuous learning のモデル昇格（champion 差し替え）は **提案のみ**で、既定では自動昇格しない。
ホールドアウト精度・較正・直近ペーパー成績の 3 条件をすべて満たした場合のみ候補として提示し、
実際の差し替えは API 経由の人間承認でのみ行う。

---

## 4. ローカル起動・検証設定

### 4.1 launch.json（`.claude/launch.json`）

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "frontend",
      "runtimeExecutable": "npm",
      "runtimeArgs": ["run", "dev", "--prefix", "frontend"],
      "port": 3001
    },
    {
      "name": "backend",
      "runtimeExecutable": ".venv/Scripts/python.exe",
      "runtimeArgs": ["-m", "uvicorn", "backend.main:app", "--port", "8002"],
      "port": 8002
    }
  ]
}
```

### 4.2 起動時に確認する常駐プロセス

「システムを起動して」という指示を受けたとき、Claude Code は以下をすべて確認し、
動いていないものだけ起動する運用にしている:

- frontend（3001）/ backend（8002）
- Redis（Docker コンテナ、Celery のブローカー兼結果バックエンド）
- Celery worker（Windows は `--pool=solo` 必須）
- Celery beat（定期タスクスケジューラ。冪等ガード実装済みのため自動起動対象）
- 外部ベクトル検索 API（未起動だと機能が接続失敗・タイムアウトを繰り返すため必須確認)

ログオン時の自動起動はユーザー環境のスケジュールタスク経由で構成している（詳細は非公開のローカル運用手順）。

### 4.3 環境変数サンプル（ダミー値、実際は `.env.example` を参照）

```dotenv
# --- 認証 ---
ML_SECRET_KEY=00000000000000000000000000000000000000000000000000000000000000
ML_PASSWORD_HASH=$2b$12$dummydummydummydummydummydummydummydummydummydumm
ML_USERNAME=admin
ML_COOKIE_SECURE=false

# --- ネットワーク ---
BACKEND_PORT=8002
FRONTEND_PORT=3001
ML_CORS_ORIGINS=http://localhost:3001,http://127.0.0.1:3001
BACKEND_PROXY_TARGET=http://127.0.0.1:8002

# --- 外部 API（任意。未設定でも起動でき機能側が「未設定」を返す） ---
JQUANTS_API_KEY=dummy-jquants-key
ANTHROPIC_API_KEY=sk-ant-dummy00000000000000000000000000
ANTHROPIC_MODEL=claude-sonnet-5
LLM_DAILY_COST_LIMIT_USD=5.0
GEMINI_API_KEY=dummy-gemini-key
GEMINI_MODEL=gemini-2.5-pro

# --- DB / Celery ---
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
CELERY_BROKER_URL=redis://127.0.0.1:6379/4
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/5

# --- Obsidian Vault（読み取り専用が原則） ---
VAULT_ROOT=C:\Users\<your-username>\Documents\ObsidianVault\StockNotes

# --- Web Push（VAPID） ---
VAPID_PUBLIC_KEY=dummy-public-key
VAPID_PRIVATE_KEY=dummy-private-key
VAPID_SUBJECT=mailto:you@example.com
```

### 4.4 検証環境

- Windows / PowerShell（コマンド連結は `;`、`&&` 不可）。Python は `.venv/Scripts/python.exe`。
- 同一 worktree をユーザーが並行編集しうるため `git add -A` は使わず対象ファイルを明示 add。
- フェーズ完了ごとにコミット & プッシュし、溜めない。

### 4.5 push 前ローカル CI

```powershell
# backend
.venv/Scripts/ruff check backend
.venv/Scripts/black --check backend
.venv/Scripts/mypy backend
.venv/Scripts/bandit -r backend --exclude backend/tests,backend/alembic
.venv/Scripts/pytest backend/tests -q

# frontend
npx tsc --noEmit
npx jest        # TZ=UTC 固定で実行
npx eslint .
npx next build
```

---

## 5. AI コーディング特有のセキュリティ運用

- 決定木的なドメイン制約（配色・数値の向き・単位・ホライズン定義など）は暗黙知に頼らず
  `CLAUDE.md` に明文化し、モデルが「一般的なデフォルト」に引っ張られるのを防ぐ。
- 外部由来テキストのプロンプト注入境界（§3.3）はコード上の一箇所に集約し、テストで固定する。
  新しい外部データソースを追加するたびに同じ境界原則をレビューする。
- 自動売買・自動発注・自動ブローカー接続は**アーキテクチャレベルで作らない**（Out of Scope）。
  AI の役割は提案・分析・通知に限定し、実行は常に人間の承認を経由させる。
- モデルの自動昇格・自動 config 変更はデフォルト OFF。安全装置としての予算上限はあっても、
  それ自体を目標化させない（自己保存的な最適化をさせない）。

---

## 6. メモリシステム（リポジトリ横断の永続コンテキスト）

Claude Code は `~/.claude/projects/<repo>/memory/` 配下に、セッションをまたいで参照される
永続メモリを保持する。種別は 4 つ:

| 種別 | 内容 |
|:--|:--|
| user | ユーザーの役割・目標・知識レベル |
| feedback | 過去に受けた修正・承認された非自明な判断（理由付き） |
| project | 進行中の作業・意思決定の背景（Why） |
| reference | 外部システム（Issue トラッカー・ダッシュボード等）へのポインタ |

このメモリはコード規約やアーキテクチャそのものは保存しない（コードを読めば分かるため）。
保存するのは「コードから読み取れない文脈」に限定している。

---

## 7. このドキュメントの位置づけ

- 本ファイルは `docs/public/` 配下に置かれた **公開用サンプル**であり、プロジェクトの継続的な
  単一情報源ではありません。単一情報源は非公開の `CLAUDE.md`（プロジェクト層）と `~/.claude/`
  （グローバル層）です。
- 過去に `CLAUDE_HARNESS.md` という類似ファイルをリポジトリ直下に置いていましたが、
  `CLAUDE.md` の内容をほぼ丸ごと複製し、更新が反映されず内部矛盾を起こしたため削除した経緯が
  あります。同じ轍を踏まないよう、本ファイルは「ある時点のスナップショットを公開用に要約したもの」
  と明記し、`docs/` 配下（as-built ドキュメント置き場）に置いています。
