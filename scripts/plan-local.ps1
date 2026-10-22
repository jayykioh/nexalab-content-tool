$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backend = [IO.Path]::GetFullPath((Join-Path $repoRoot "..\nexalab-be"))
if (-not (Test-Path (Join-Path $backend "scripts\content-release.ts"))) {
    throw "NexaLab BE checkout not found at $backend"
}

$backendEnv = Join-Path $backend ".env"
$envFile = if (Test-Path $backendEnv) { Get-Content $backendEnv } else { @() }
foreach ($name in @("DATABASE_URL", "DIRECT_URL")) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if (-not $value) {
        $line = $envFile | Where-Object { $_ -match "^\s*$name\s*=" } | Select-Object -First 1
        if ($line -match "^\s*$name\s*=\s*['`"]?(.*?)['`"]?\s*$") {
            $value = $Matches[1]
        }
    }
    if (-not $value) { throw "Cannot verify $name; refusing local plan." }

    $hostName = ([Uri]$value).Host
    if ($hostName -notin @("localhost", "127.0.0.1", "::1")) {
        throw "Refusing local plan: $name points to a remote database host. Verify the target before using the backend CLI."
    }
}

Push-Location $repoRoot
try {
    & uv run nexalab-content plan examples/synthetic-pilot --backend $backend --target development
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
