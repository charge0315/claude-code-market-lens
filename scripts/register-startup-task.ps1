# Alpha Forge の4プロセス（backend / Celery worker / Celery beat / frontend）を、
# ログオン時に自動起動する Windows タスクスケジューラのタスクを登録する
# （Market Lens `scripts/register-startup-task.ps1` と同じ設計）。
#
# ユーザー指示: Docker Desktop → Redis サービス → Vector API サービス → Vector Watcher
# （いずれも obsidian-knowledge-base-creator プロジェクトが管理する既存のログオン時タスク、
# `KB-Service-Redis` / `KB-Service-VectorApi` / `KB-Vault-VectorWatch`）が起動した後に
# Alpha Forge を起動する。Task Scheduler には「他タスク完了後に起動」というトリガーが
# 無いため、scripts/wait-for-kb-services.ps1 が各サービスの実際の生存確認
# （Docker daemon 応答 / Redis:6379 疎通 / Vector API:8077 疎通 / KB-Vault-VectorWatch
# タスクの Running 状態）をポーリングして待つ方式で順序を保証する
# （scripts/start-with-dependencies.ps1 経由）。
#
# 使い方（管理者権限の pwsh で1回だけ）:
#   .\scripts\register-startup-task.ps1
# 解除:
#   .\scripts\register-startup-task.ps1 -Unregister
#
# 注意:
# - タスクは「ログオン時」に発火する（KB-Service-* / KB-Vault-VectorWatch と同じトリガー種別）。
#   PC 起動＝ログオンではない環境では -AtStartup 版に読み替えること。
# - start.ps1 は .run\pids.json が残っていると「起動中」とみなして exit 1 する。前回が
#   正常終了（stop.ps1）していれば問題ないが、クラッシュ後は手動で .run\pids.json を削除してから
#   ログオンし直すこと。
# - 必ず PowerShell 7 (pwsh) 前提（start.ps1 が日本語コメント入り UTF-8 のため）。

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$taskName = "AlphaForge-Autostart"
$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $repoRoot "scripts\start-with-dependencies.ps1"
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "タスク '$taskName' を解除しました。"
    } else {
        Write-Host "タスク '$taskName' は登録されていません。"
    }
    return
}

if (-not $pwsh) {
    throw "pwsh (PowerShell 7) が見つかりません。start.ps1 は pwsh 前提です。"
}
if (-not (Test-Path $startScript)) {
    throw "$startScript が見つかりません。"
}

# 既存タスクがあれば作り直す（冪等）
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`"" `
    -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# KB系サービスの起動待ちで数分かかりうるため、実行時間の上限は設けない。
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Alpha Forge の4プロセスをログオン時に起動する（Docker Desktop/Redis/Vector API/Vector Watcher の起動を待ってから scripts/start.ps1 を実行）" | Out-Null

Write-Host "タスク '$taskName' を登録しました（ログオン時に $startScript を実行）。"
Write-Host "今すぐ動作確認する場合: Start-ScheduledTask -TaskName $taskName"
