param (
    [string]$Workspace = "workspaces/m1-khtn8-acceptance",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

# Chuyển về thư mục gốc của repository
$repoRoot = $PSScriptRoot
Push-Location $repoRoot

try {
    # 1. Cài đặt / đồng bộ thư viện
    Write-Host "[1/2] Syncing environment with uv..." -ForegroundColor Cyan
    & uv sync

    # 2. Khởi chạy Python BE server và mở HTML UI trên trình duyệt
    Write-Host "[2/2] Launching NexaLab Studio at http://127.0.0.1:$Port ($Workspace)..." -ForegroundColor Green
    & uv run nexalab-content studio $Workspace --port $Port
}
finally {
    Pop-Location
}
