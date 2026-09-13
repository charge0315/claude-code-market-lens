# Alpha Forge の自動起動専用: Docker Desktop → Redis（market-lens-redis コンテナ、Alpha
# Forge も DB番号4/5で共用） → Vector API（kb_creator, :8077） → Vector Watcher
# （KB-Vault-VectorWatch タスク）の順に起動を待ってから戻る（ユーザー指示）。
#
# 各段はポーリングし、タイムアウトしたら警告を出すだけで次へ進む（obsidian-knowledge-base-creator
# の tasks/lib/service_helper.ps1 と同じ「ダメでも進む」フェイルソフト方式。Redis/KB系が
# 落ちていても Alpha Forge 自体は起動できるようにする、docs/operations.md §1 の既存方針と同じ）。
#
# 単体では使わない — scripts/start-with-dependencies.ps1 から呼ばれる想定。
# Docker Desktop 自体の起動はここでは行わない（Docker Desktop 側の「ログイン時に起動」設定を
# 前提とする、obsidian-knowledge-base-creator の各 start_*.ps1 と同じ前提）。

param(
    [int]$TimeoutSec = 300,
    [int]$IntervalSec = 5
)

function Wait-DockerReady {
    param([int]$TimeoutSec, [int]$IntervalSec)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        try {
            $null = docker info 2>&1
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch {}
        Start-Sleep -Seconds $IntervalSec
        $elapsed += $IntervalSec
    }
    return $false
}

function Wait-TcpPort {
    param([string]$ComputerName, [int]$Port, [int]$TimeoutSec, [int]$IntervalSec)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $client.Connect($ComputerName, $Port)
            $client.Close()
            return $true
        } catch {
            Start-Sleep -Seconds $IntervalSec
            $elapsed += $IntervalSec
        }
    }
    return $false
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec, [int]$IntervalSec)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Seconds $IntervalSec
        $elapsed += $IntervalSec
    }
    return $false
}

function Wait-ScheduledTaskRunning {
    param([string]$TaskName, [int]$TimeoutSec, [int]$IntervalSec)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task -and $task.State -eq "Running") { return $true }
        Start-Sleep -Seconds $IntervalSec
        $elapsed += $IntervalSec
    }
    return $false
}

Write-Host "=== Alpha Forge 依存サービスの待機開始 $(Get-Date -Format o) ==="

Write-Host "1/4 Docker Desktop の起動を待っています..."
if (Wait-DockerReady -TimeoutSec $TimeoutSec -IntervalSec $IntervalSec) {
    Write-Host "    OK"
} else {
    Write-Host "    警告: ${TimeoutSec}秒待っても Docker Desktop が応答しません。以降のチェックも失敗する見込みですが続行します。"
}

Write-Host "2/4 Redis（127.0.0.1:6379、market-lens-redis コンテナ）の起動を待っています..."
if (Wait-TcpPort -ComputerName "127.0.0.1" -Port 6379 -TimeoutSec $TimeoutSec -IntervalSec $IntervalSec) {
    Write-Host "    OK"
} else {
    Write-Host "    警告: ${TimeoutSec}秒待っても Redis が応答しません。celery-beat 経由の自走機能は動きません。"
}

Write-Host "3/4 Vector API（http://127.0.0.1:8077、kb_creator）の起動を待っています..."
if (Wait-HttpOk -Url "http://127.0.0.1:8077/openapi.json" -TimeoutSec $TimeoutSec -IntervalSec $IntervalSec) {
    Write-Host "    OK"
} else {
    Write-Host "    警告: ${TimeoutSec}秒待っても Vector API が応答しません。ナレッジベース検索は関連ノート無しにフォールバックします。"
}

Write-Host "4/4 Vector Watcher（KB-Vault-VectorWatch タスク）の起動を待っています..."
if (Wait-ScheduledTaskRunning -TaskName "KB-Vault-VectorWatch" -TimeoutSec $TimeoutSec -IntervalSec $IntervalSec) {
    Write-Host "    OK"
} else {
    Write-Host "    警告: ${TimeoutSec}秒待っても Vector Watcher タスクが Running になりません。"
}

Write-Host "=== 依存サービスの待機終了 $(Get-Date -Format o) ==="
