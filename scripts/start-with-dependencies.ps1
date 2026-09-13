# システム起動時の自動実行専用エントリポイント（scripts/register-startup-task.ps1 が登録する
# タスクから呼ばれる）。Docker Desktop → Redis → Vector API → Vector Watcher の順に起動を
# 待ってから Alpha Forge 本体（scripts/start.ps1）を起動する（ユーザー指示）。
#
# 手動起動時は待機不要なので、直接 .\scripts\start.ps1 を使うこと。

$ErrorActionPreference = "Continue"
$scriptDir = $PSScriptRoot

& (Join-Path $scriptDir "wait-for-kb-services.ps1")
& (Join-Path $scriptDir "start.ps1")
