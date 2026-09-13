# scripts/start.ps1 が起動した4プロセス（backend / Celeryワーカー / Celery beat / frontend）を
# まとめて停止する（Market Lens `scripts/stop.ps1` と同じ設計）。
#
# 使い方: .\scripts\stop.ps1
#
# 注意: 必ず PowerShell 7 (pwsh) で実行すること（scripts/start.ps1 と同じ制約）。

$ErrorActionPreference = "Continue"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $repoRoot ".run\pids.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "$pidFile が見つかりません。start.ps1で起動していないか、既に停止済みです。"
    exit 0
}

$pidMap = Get-Content $pidFile -Raw | ConvertFrom-Json

foreach ($name in @("backend", "celery", "celeryBeat", "frontend")) {
    $procId = $pidMap.$name
    if (-not $procId) { continue }

    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "$name (PID $procId) は既に停止しています。"
        continue
    }

    Write-Host "$name (PID $procId) を停止しています..."
    # npm run dev（Node）やCeleryワーカーはPowerShellの子プロセスを起動するため、
    # Stop-Process単体だと子プロセスが取り残されることがある。taskkill /T でツリーごと止める。
    # Celeryワーカーは実行中タスクの完了を待たず即終了する（既知の挙動、docs/operations.md §1）。
    taskkill /PID $procId /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item -Path $pidFile -Force
Write-Host "停止処理が完了しました。"
