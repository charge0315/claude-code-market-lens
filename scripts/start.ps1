# Alpha Forge の4プロセス（backend / Celeryワーカー / Celery beat / frontend）をまとめて
# バックグラウンド起動する（Market Lens `scripts/start.ps1` と同じ設計を移植）。
#
# 前提: Redis は別途起動しておくこと（このスクリプトの責務外）。未起動でもバックエンド自体は
# 起動するが、celery-beat 経由の自走機能（AIピック自動生成・売買タイミング監視・日次学習等）は
# すべて動かない（docs/operations.md §1/§4.2）。
#
# システム起動時に依存サービス（Docker Desktop → Redis → Vector API → Vector Watcher）を
# 待ってから自動実行したい場合は scripts/register-startup-task.ps1 を使うこと。
# 個別デバッグ時はこのスクリプトを直接使う。
#
# 使い方: .\scripts\start.ps1
# 停止: .\scripts\stop.ps1
#
# 注意: 必ず PowerShell 7 (pwsh) で実行すること（日本語コメント入り UTF-8 のため、
# Windows PowerShell 5.1 はトークナイズに失敗する — Market Lens と同じ制約）。

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repoRoot ".run"
$logDir = Join-Path $repoRoot "logs"
$pidFile = Join-Path $runDir "pids.json"

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    Write-Host "$pidFile が既に存在します。既に起動中の可能性があります。先に .\scripts\stop.ps1 を実行してください。"
    exit 1
}

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$celeryExe = Join-Path $repoRoot ".venv\Scripts\celery.exe"

if (-not (Test-Path $pythonExe)) {
    throw "$pythonExe が見つかりません。backend の venv をセットアップしてください。"
}
if (-not (Test-Path $celeryExe)) {
    throw "$celeryExe が見つかりません。"
}

Write-Host "バックエンドを起動しています..."
$backend = Start-Process -FilePath $pythonExe `
    -ArgumentList @("-m", "uvicorn", "backend.main:app", "--port", "8002") `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput (Join-Path $logDir "backend.out.log") `
    -RedirectStandardError (Join-Path $logDir "backend.err.log") `
    -WindowStyle Hidden -PassThru

Write-Host "Celeryワーカーを起動しています（ピック生成・保有監視・学習バッチ・通知・EODレビュー等）..."
# Windows は `worker --pool=solo` 必須（Market Lens と同じ制約、docs/operations.md §1）。
$celery = Start-Process -FilePath $celeryExe `
    -ArgumentList @("-A", "backend.celery_app", "worker", "--pool=solo", "--loglevel=info") `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput (Join-Path $logDir "celery.out.log") `
    -RedirectStandardError (Join-Path $logDir "celery.err.log") `
    -WindowStyle Hidden -PassThru

Write-Host "Celery beat（定期実行スケジューラ）を起動しています..."
# beat は単一インスタンスのみ起動すること（二重起動するとスケジュールされたタスクが重複発火する）。
# Windows は `worker -B`（beat 埋め込み）を拒否するため必ずワーカーとは別プロセスにする。
$celeryBeat = Start-Process -FilePath $celeryExe `
    -ArgumentList @("-A", "backend.celery_app", "beat", "--loglevel=info") `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput (Join-Path $logDir "celery-beat.out.log") `
    -RedirectStandardError (Join-Path $logDir "celery-beat.err.log") `
    -WindowStyle Hidden -PassThru

Write-Host "フロントエンドを起動しています..."
$frontend = Start-Process -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev") `
    -WorkingDirectory (Join-Path $repoRoot "frontend") `
    -RedirectStandardOutput (Join-Path $logDir "frontend.out.log") `
    -RedirectStandardError (Join-Path $logDir "frontend.err.log") `
    -WindowStyle Hidden -PassThru

@{ backend = $backend.Id; celery = $celery.Id; celeryBeat = $celeryBeat.Id; frontend = $frontend.Id } |
    ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8

Write-Host "起動しました（PID: backend=$($backend.Id), celery=$($celery.Id), celeryBeat=$($celeryBeat.Id), frontend=$($frontend.Id)）。ログ: $logDir"
Write-Host "起動確認中（/health）..."

$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8002/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        continue
    }
}

if ($healthy) {
    Write-Host "バックエンドの起動を確認しました（DB/Redis疎通OK）。自走スケジュールが有効です。"
} else {
    Write-Host "警告: /health が200を返しませんでした。Redisが未起動の可能性があります。"
    Write-Host "学習/自走スケジュール（AIピック自動生成・売買タイミング監視等）が影響を受けます。ログを確認してください: $logDir"
}

Write-Host "フロントエンド: http://localhost:3001"
Write-Host "停止するには: .\scripts\stop.ps1"
