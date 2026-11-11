[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$Port = 8000,
    [string]$DatabasePath = '',
    [switch]$NoBrowser,
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    & python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.13+ is required. Install Python and try again.' }
    $Install = $true
}
if ($Install) {
    & $pythonPath -m pip install --disable-pip-version-check --upgrade pip==26.2.2
    if ($LASTEXITCODE -ne 0) { throw 'Python installer update failed.' }
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $pythonPath -c 'import fastapi, sqlalchemy, argon2, uvicorn, psycopg'
if ($LASTEXITCODE -ne 0) { throw 'Dependencies are missing. Run scripts\start.ps1 -Install.' }
# A local start is deliberately self-contained; it never connects to a cloud DB.
$env:APP_ENV = 'development'
$env:DEMO_MODE = 'true'
$env:COOKIE_SECURE = 'false'
$env:PUBLIC_ORIGIN = "http://127.0.0.1:$Port"
$env:ALLOWED_HOSTS = '127.0.0.1,localhost'
$dbPath = if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    Join-Path $projectRoot 'atlas.db'
} else {
    $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DatabasePath)
}
if (-not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($dbPath)) -PathType Container)) {
    throw 'The directory for the local SQLite database must exist.'
}
$env:DATABASE_URL = 'sqlite:///' + $dbPath.Replace([IO.Path]::DirectorySeparatorChar, [char]'/')
Write-Host "ATLAS Campus: http://127.0.0.1:$Port"
Write-Host 'Contest concept. All data is fictional. Press Ctrl+C to stop; your requests remain saved.'
$portProbe = [Net.Sockets.TcpClient]::new()
try {
    $portProbe.Connect('127.0.0.1', $Port)
    throw "Port $Port is already in use. Choose another with -Port."
} catch [Net.Sockets.SocketException] {
    # A refused connection is expected before this launcher starts its own server.
} finally { $portProbe.Dispose() }
$browserJob = $null
if (-not $NoBrowser) {
    $browserJob = Start-Job -ArgumentList $Port -ScriptBlock {
        param($ServerPort)
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ServerPort/api/ready" -TimeoutSec 2
                if ($health.ok) { Start-Process "http://127.0.0.1:$ServerPort"; break }
            } catch { }
            Start-Sleep -Milliseconds 500
        }
    }
}
try {
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port $Port
    $serverExitCode = $LASTEXITCODE
} finally {
    if ($browserJob) { Stop-Job -Job $browserJob; Remove-Job -Job $browserJob }
}
exit $serverExitCode
