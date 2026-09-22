# CLAUDE_HARNESS.md — Alpha Forge 統合エージェントハーネス仕様書

> **概要**  
> 本ファイルは、AI コーディングエージェント（Claude Code）が日本株 AI 銘柄ピック＆継続学習端末「**Alpha Forge**（`claude-code-market-lens`）」において、自律的かつ安全・高品質に開発・運用・保守を行うための**実行ハーネス設定・環境規約・ガードレールを 1 ファイルに統合・表現した仕様書**です。

---

## 1. エージェント運用原則と基本規約 (Operating Principles & Core Rules)

### 1.1 基本姿勢と動作モード
- **自律的フルスタック開発**: Claude Code は調査、設計、実装、テスト作成、検証、リファクタリングを自走して進める。
- **可逆操作の自走原則**: コード編集、新規ファイル作成、テスト実行、リンタ/型チェック実行、ローカル検証、コードベース調査などの**可逆な作業はユーザー確認を取らずに自走**する。
- **不可逆・重要操作の確認必須**:
  - `git commit` / `git push` / ブランチマージ / PR 作成
  - 本番/外部サービスへのデータ送信や投稿（note.com の公開ボタン操作含む）
  - ファイル削除、既存永続データの破壊的変更
  - 認証情報・シークレットの設定変更
  - 予算上限の引き上げや恒久的なセキュリティポリシー緩和
- **言語規約**:
  - 会話、思考トレース、ドキュメント（`docs/`, `plans/`, `README.md` など）、コード内コメント、コミットメッセージはすべて**日本語**とする。
  - コードコメントは「何をしているか（What）」ではなく「**なぜその実装にしたのか（Why）**」を記述する。
- **Zero Linter/Compiler Warnings（警告完全ゼロ規約）**:
  - リンタ（Ruff, ESLint）、型検査（Mypy, `tsc --noEmit`）、セキュリティ検査（Bandit）、テスト（Pytest, Jest, Playwright）の警告・エラーを未解決のまま放置することは一切許可されない。
  - 警告はコード修正で解消するか、正当な理由を明記した上で明示抑制する（`# noqa: X — 理由` / `// eslint-disable-line X — 理由`）。

### 1.2 OS & 実行環境制約 (Windows / PowerShell)
- **PowerShell コマンド連結ルール**:
  - Windows PowerShell 環境のため、コマンドの連結には **必ずセミコロン `;` を使用する**（**`&&` は絶対に使用しない**）。
- **Python インタープリタ**:
  - Python 実行はリポジトリローカルの仮想環境 `.venv/Scripts/python.exe`（Python 3.11）を使用する。
  - Celery 実行は `.venv/Scripts/celery.exe` を使用する。
- **Node.js / フロントエンド**:
  - Node.js 環境下で `npm run dev --prefix frontend`, `npx tsc --noEmit`, `TZ=UTC npx jest` などを実行。

---

## 2. ランタイム & プロセス管理ハーネス (Runtime & Process Matrix)

### 2.1 ポートマッピングとプロセス一覧

| プロセス | ランタイム / コマンド | ポート | 役割 / 備考 |
|:--|:--|:--|:--|
| **Frontend** | `npm run dev --prefix frontend` | **3001** | Next.js 16 (App Router) + Vanilla CSS |
| **Backend** | `.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8002` | **8002** | FastAPI サーバー（REST / WebSocket / SSE） |
| **Redis** | Docker コンテナ `market-lens-redis` | **6379** | Celery ブローカー（DB 4）および結果バックエンド（DB 5） |
| **Celery Worker** | `.venv/Scripts/celery.exe -A backend.celery_app worker --pool=solo --loglevel=info` | — | 非同期タスク処理（Windows では `--pool=solo` 必須） |
| **kb_creator** | `tasks/start_vector_api.ps1` (外部リポジトリ) | **8077** | ベクトル検索 API + Qdrant（Obsidian ノート検索用） |
| **Celery Beat** | `.venv/Scripts/celery.exe -A backend.celery_app beat` | — | **常時自動起動は禁止**（後述の安全ルール参照） |

### 2.2 `.claude/launch.json` 定義
Claude Code のプロセス起動連携は `.claude/launch.json` を通じて管理される。

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

### 2.3 プロセスライフサイクル・安全ガードルール
1. **「システム起動して」プロトコル**:
   - 起動確認順序: Redis (Docker) → kb_creator (8077) → Backend (8002) → Frontend (3001) → Celery Worker (`--pool=solo`)。
   - 既に動いているプロセスは二重起動せず、落ちているもののみを選択して起動する。
2. **Celery Beat 自動起動の絶対禁止**:
   - `celery-beat` は通常の「システム起動」対象に**含めてはならない**。
   - **理由**: 初回起動時や長期停止後に beat を起動すると、実行履歴欠落により過去の全定期タスク（ピック生成、大規模再学習バッチ、ドリフト検知等）が一斉に「未実行」とみなされて同時発火し、ピックの二重生成やリソース枯渇を引き起こすため。beat 起動が必要な場合はユーザーに副作用を明示し、承認を得てから起動する。
3. **外部ベクトル検索サービス（kb_creator）の死活監視**:
   - `services/vault/knowledge_search_client.py` はポート 8077 に接続する。未起動時は全銘柄で接続タイムアウトが発生しピック生成が致命的に遅延するため、事前にポートオープンを確認する。

---

## 3. セキュリティ & ガードレールハーネス (Security & Safety Guardrails)

### 3.1 プロンプトインジェクション多層防御境界（最重要規約）
外部由来のテキストに悪意ある指示文（間接プロンプトインジェクション）が含まれていても、AI の意思決定や売買提案が改ざんされないよう、厳格なデータ境界を強制する。

```
[外部ソース (Vault, ニュース, 四季報)] 
       │
       ▼ (生テキスト本文は遮断)
[メタデータ抽出層] ──> frontmatter / 数値 / enum / 検証済みコードのみ
       │
       ▼
[隔離 LLM (ニュースセンチメント / トレンド抽出)]
       │
       ▼ (自由記述 reasoning は UI 表示用 rationale_struct へ隔離)
[スコア / enum のみ転送]
       │
       ▼
[コア LLM (propose_stock_pick)] ──> 買値 / 損切 / 売値 の 3 値付き提案
```

1. **生テキスト本文の遮断**:
   - Obsidian Vault ノート（`Tickers/*.md`, `Daily/*.md`）、生ニュース本文、四季報本文の自由記述は **LLM プロンプトへ絶対に注入しない**。
   - 注入が許可されるのは frontmatter（財務指標等の構造化データ）および検証済みの数値・enum のみ。
2. **間接インジェクションのロンダリング防止**:
   - ニュース見出しのセンチメント判定（`services/scoring/llm_news_sentiment_service.py`）: 見出し本文を読むのはこの隔離 LLM のみとし、本体の `propose_stock_pick` へは判定結果（`sentiment_score`, `confidence` 等）のみを渡す。自由記述の `reasoning` を本体プロンプトへ転送しない。
   - トレンド分析（`services/data/trend/context.py`）: 生ニュースを構造化した `Trend` オブジェクトから、本体プロンプトへ渡す前に `theme_name` や `summary` 等の自由記述を完全に除去し、数値・enum・検証済み銘柄コードのみを渡す（2026-09-18 強化策）。
3. **ナレッジ検索（kb_creator / Qdrant）の防御境界**:
   - ベクトル検索結果の本文（`text`）はクライアント関数の戻り値から除外し、関連ノートのパス（`note_path`）の発見にのみ利用する。プロンプトへ渡す情報は、そのパスから改めて抽出した frontmatter のみとする。
4. **継続学習の自己完結原則**:
   - 継続学習の教師信号には**自システムの実測値（株価・リターン・勝敗）のみ**を使用する。外部テキストや外部のアナリスト見解を学習根拠にしない。

### 3.2 金融法規 & 法的コンプライアンスハーネス
1. **ブローカー実発注の完全排除**:
   - アプリケーションはいかなる証券会社 API（発注 API）とも接続せず、発注機能・自動約定機能を一切実装しない。
2. **投資助言業の抵触防止**:
   - すべての出力は「アルゴリズムによる分析結果・参考情報」として提示し、個別断定的な投資勧誘文言を出力しない。
   - UI 全画面のフッタに免責事項を常設する。
3. **完全承認制ポートフォリオ（Human-in-the-Loop）**:
   - 保有銘柄に対する売買タイミング判定は「提案チケット」の発行にとどめ、ユーザーの明示的な承認・却下・約定報告によってのみポートフォリオ状態を更新する。
4. **note 下書きへの売買価格非掲載ルール**:
   - note 記事生成時は、投資助言業抵触を回避するため `entry` / `stop` / `target` の具体的な 3 値をプロンプトへ渡さず、記事本文にも記載しない（根拠と市場分析の共有に限定）。

### 3.3 データ保全 & 外部連携ガード
1. **Obsidian Vault の読み取り専用原則**:
   - Vault ルート（`VAULT_ROOT`: `C:\Users\charg\Documents\Personal Space\10_Stock`）は原則読み取り専用。
   - 書き込みは Alpha Forge 専用ディレクトリ（`Daily/AlphaForge/<日付>/`）に限定し、既存ノートの上書き・破壊を行わない。
2. **四季報スクレイピングの恒久禁止**:
   - 東洋経済オンライン等のスクレイピングは有料会員規約（自動取得禁止・違約金条項）に抵触するため**実装を恒久的に禁止**する。

---

## 4. ドメイン制約 & ビジネスロジック・インバリアント (Domain Invariants)

エージェントがコード変更・機能追加を行う際、絶対に破壊してはならないドメインルール群：

### 4.1 日本株市場仕様
- **タイムゾーン**: すべての時刻処理・ログ・スケジューリングは **JST (Asia/Tokyo)** を基準とする。
- **取引時間**: 東証の前場（9:00–11:30）、後場（12:30–15:00）、大引けは **15:00**。シグナル監視は平日 9:00–15:30。
- **休場日・祝日ガード**:
  - 日本の祝日・市場休場日にはシグナル判定やピック生成を停止するか、前営業日終値ベースであることを明示する。休場日のデータを本日の値動きと偽って処理してはならない。
- **銘柄コード体系**: 東証上場銘柄コードは数字 **4 桁**（例: `7203`）。`.T` やプレフィックスを内部モデルで付与しない。
- **ボラティリティ指標**: 日経VI は yfinance の制約上、CBOE VIX（`^VIX`）を代替指標として使用する。

### 4.2 騰落色規約（日本国内証券標準）
- **上昇・利益 = 赤**、**下落・損失 = 緑**。
- 海外ツール標準（緑=上昇）で実装することを厳禁とし、必ず CSS デザイントークン `--color-gain`（赤系）/ `--color-loss`（緑系）/ `--color-flat` を使用する。

### 4.3 3 値ブラケットの必須化と厳格検証
- AI が売買を提案するすべての機能（中長期ピック、短期ピック、ポートフォリオ買い増し判定）において、以下 3 値を必須出力とする：
  1. **推奨買値 (`entry`)**
  2. **損切ライン (`stop`)**
  3. **推奨売値 (`target`)**
- バックエンドのドメイン検証により以下を厳格に強制し、満たさない提案は却下または自動補正する：
  $$\text{stop} < \text{current\_price} < \text{target} \quad \text{かつ} \quad \text{stop} < \text{entry} < \text{target}$$

### 4.4 確度の事後較正（Calibration）
- LLM や ML モデルが出力する確度（0–100）はそのまま UI に表示せず、**Isotonic Regression / Platt Scaling** により過去の実測勝率に事後較正してから提示する。
- UI 上では「確度バケット（高/中/低）」とともに「過去の同バケット実測勝率」を併記する。

### 4.5 継続学習ループ（ML Harness）
1. **完全予測台帳 (`prediction_ledger`)**:
   - 予測時点の特徴量スナップショット（`feature_snapshot`）、寄与度、モデルバージョン、3 値、確度をイミュータブルに記録。
2. **複数ホライズン決着記録 (`pick_outcomes`)**:
   - 短期（1, 2, 3 営業日）、中長期（5, 20, 60 営業日）の株価推移を追跡し、利確/損切到達順序、MFE/MAE、TOPIX 超過リターンを記録。
3. **ウォークフォワード時系列検証**:
   - 未来情報のリークを防止するため、時系列分割クロスバリデーション（Walk-Forward Validation）のみを適用。
4. **Champion / Challenger 運用と昇格提案ゲート**:
   - 本番モデル（Champion）に対し、新モデル（Challenger）を Shadow 推論で並走させる。
   - 昇格条件: ホールドアウト評価で Champion 超過 かつ 較正悪化なし かつ 直近 20 営業日のペーパー成績非劣化。
   - **自動昇格は行わず、管理画面からの人間による承認を必須とする**（`MODEL_AUTO_PROMOTE=false` 既定）。
5. **Point-in-Time (PIT) データの backward as-of 結合**:
   - 過去時点のファンダメンタル・センチメント特徴量復元には `pandas.merge_asof(direction="backward")` を使用し、未来データの混入を構造的に遮断する。

---

## 5. アーキテクチャ & コード設計規約 (Code Standards)

### 5.1 フロントエンド規約 (Next.js 16 + TypeScript)
- **TypeScript**: `strict: true`、`any` 型の使用を禁止。インターフェースは明示的に型定義。
- **インポートパス**: 絶対パス `@/...`（`tsconfig.json` の paths）を使用する。
- **スタイリング**:
  - **Vanilla CSS のみ採用（Tailwind CSS は使用禁止）**。
  - デザイントークンは `frontend/src/app/tokens.css` を単一の真実源とする。
  - カラーテーマは「Organic（明るいクリーム色 `#f5ead8`、プライマリアクセント `#c67139`、オリーブセカンダリ `#7a8a5e`）」。
  - アニメーションは GPU アクセラレーションが効く `transform` と `opacity` のみ。
  - レスポンシブ `@media` ブレークポイントは **640 / 768 / 900 / 1280 px のみ**に制限。
- **コンポーネント & UI**:
  - 生の `<table>` タグは直接書かず、アクセシビリティ対応済みの `@/components/ui/DataTable` を使用する（`caption` 必須）。
  - 数値表示は `font-variant-numeric: tabular-nums` で等幅右寄せ。
  - セキュリティ: nonce ベースの CSP（`frontend/src/proxy.ts` / `middleware.ts`）。

### 5.2 バックエンド規約 (FastAPI + Python 3.11)
- **型安全性**: 全関数の引数・戻り値に型アノテーションを付与。`Any` は禁止（必要時は `object` + 型ナローイング）。
- **データモデル**: Pydantic v2 を使用し、イミュータビリティを保つため原則 `frozen=True` を指定。
- **非同期処理**: I/O 操作（DB、外部 API、HTTP 通信）は `async/await` を徹底。
- **モジュール分割と行数制限**:
  - 1 ファイルの行数は 200〜400 行を目安とし、**最大 800 行を厳格な上限**とする。800 行を超える場合はモジュール分割を実施する。
- **マルチ LLM プロバイダ抽象化**:
  - LLM 呼び出しは `services/llm/registry.py` を経由し、機能ごとに Anthropic / OpenAI / Gemini を動的解決する。直接ハードコードプロバイダ呼び出しを行わない。
- **並列処理アーキテクチャ**:
  - Celery Worker 自体は Windows 安定性のため `--pool=solo` で稼働させ、機械学習等の重い並列計算はタスク内部で `ProcessPoolExecutor` を明示的に起動して処理する。テスト時はスレッドプールへ差し替え可能な設計とする。

---

## 6. テスト・検証 & CI ハーネス (Verification & Quality Gates)

Claude Code はコード変更後、以下の検証ハーネスを実行し、全テスト通過と警告ゼロを確認してから作業を完了すること。

### 6.1 ローカル CI 実行チェックリスト

#### バックエンド検証コマンド
```powershell
# 1. コードフォーマット & リント
.venv/Scripts/ruff.exe check backend;
.venv/Scripts/black.exe --check backend;

# 2. 静的型検査
.venv/Scripts/mypy.exe backend;

# 3. セキュリティ脆弱性検査
.venv/Scripts/bandit.exe -r backend --exclude backend/tests,backend/alembic;

# 4. 単体・結合テスト実行
.venv/Scripts/pytest.exe backend/tests -q;

# 5. OpenAPI スキーマ整合性検証
.venv/Scripts/python.exe scripts/export_openapi.py
```

#### フロントエンド検証コマンド
```powershell
# 1. TypeScript 型検査
npx tsc --noEmit;

# 2. 単体・コンポーネントテスト
$env:TZ="UTC"; npx jest;

# 3. ESLint 静的解析
npx eslint .;

# 4. 本番ビルド検証
npx next build
```

### 6.2 テスト環境分離ハーネス
- **DB 隔離**: データベース書き込みを伴うバックエンドテストは、`backend/tests/conftest.py` の `isolated_db` または `initialized_db` フィクスチャを使用し、テストごとに DB ファイル・テーブルを完全分離する。
- **外部通信モック**: yfinance, J-Quants, LLM API, Web Push などの外部通信はテスト内で必ずモック（`unittest.mock` / `respx`）し、外部障害でテストが壊れないようにする。

### 6.3 Git コミット規約
- **`git add -A` の絶対禁止**: 他のプロセスやユーザーが並行編集している作業ツリーを巻き込まないため、コミット対象ファイルを個別に明示指定する（例: `git add backend/services/foo.py backend/tests/test_foo.py`）。
- **コミットメッセージ形式**: 日本語で Conventional Commits に準拠（`feat: ...`, `fix: ...`, `refactor: ...`, `test: ...`）。

---

## 7. 定常運用プレイブック (Operational Playbooks)

### 7.1 「システム起動して」フロー
ユーザーから「システム起動して」「サーバー立ち上げて」と指示された場合の実行手順：
1. **Redis コンテナ確認**: `docker ps` で `market-lens-redis` を確認。停止していれば `docker start market-lens-redis`。
2. **外部ベクトル API 確認**: `Test-NetConnection -ComputerName 127.0.0.1 -Port 8077` で kb_creator を確認。
3. **Backend / Frontend 確認**: ポート 8002 / 3001 のリッスン状況を確認し、未起動なら `.claude/launch.json` のコマンドでバックグラウンド起動。
4. **Celery Worker 起動**: 未起動なら `.venv/Scripts/celery.exe -A backend.celery_app worker --pool=solo --loglevel=info` をバックグラウンド起動。
5. **Celery Beat は起動しない**: ユーザーに「Celery Beat はタスク多重発火防止のため自動起動していません」と報告。

### 7.2 「今日のノート」手動執筆ワークフロー
「今日のノート」「今日のnote」と指示された場合、対話型で note.com 向け記事を作成する：
1. **休場日・前日決着・本日ピック確認**: API 経由でデータ取得（休場日であれば記事内に明記）。
2. **スクリーンショット取得**: `claude-in-chrome` を用い、ダッシュボード、AI 思考トレース、チャートを撮影し `docs/note/YYYY-MM-DD/images/` に保存（UI 上のアプリ名ロゴ等はトリミングまたはマスク）。
3. **表の画像化**: ピック一覧表・レーダー比較を matplotlib で画像化（日本語フォント: Yu Gothic / Meiryo）。
4. **note.txt 執筆**: note.com エディタ仕様に合わせ、マークダウンではなく**プレーンテキスト**で執筆（見出し記号 `#` や `**` は使わず、`1. 🌍 見出し` や `【】` を使用）。アプリ固有名称「AlphaForge」は出さない。
5. **下書き保存の徹底**: note.com への反映は下書き保存までとし、**「投稿/公開」ボタンは絶対に押さない**。

### 7.3 日次ログ集約 & EOD レビュー
- 毎日 17:00 に celery-beat または手動トリガーにより、当日の候補プール全銘柄のスコア、LLM 見解、3 値、検証結果、決着、再学習結果を Markdown 形式で `Daily/AlphaForge/<日付>/pipeline_log.md` へ永続化する。

---

## 8. エージェント自己診断 & トラブルシューティング

| 異常事象 | 主因 | 対処手順 |
|:--|:--|:--|
| ピック生成が数分以上タイムアウトする | kb_creator (8077) が未起動でナレッジ検索がリトライを繰り返している | ポート 8077 の状態を確認し、外部サービスを起動するか mock / スタブで回避する |
| Celery でタスクが実行されない | Windows で `--pool=solo` が指定されていないか、Redis が停止している | Redis の Docker 状態確認後、Worker を `--pool=solo` オプション付きで再起動する |
| テストで子プロセスエラーが発生する | `ProcessPoolExecutor` にテストのモック環境が引き継がれていない | `weekly_learning_service.py` の `_create_worker_pool` がテスト用スレッドプールに差し替えられているか確認する |
| ピックの価格関係エラーが多発する | `stop < entry < target` の検証に引っかかっている | ブラケット計算ロジック（ATR / 支持抵抗線算出）の最小幅・最大幅パラメータを点検する |
| note.com に貼ると番号が消える | 数字+ピリオド（`2. `）により note エディタがリスト変換を発動している | 行頭を全角数字にするか、絵文字を先頭に置く形式に置換する |
