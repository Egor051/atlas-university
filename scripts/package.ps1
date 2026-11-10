[CmdletBinding()]
param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'dist' }
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archivePath = Join-Path $outputRoot "ATLAS-campus-source-$timestamp.zip"
$partialPath = "$archivePath.partial"
$allowedRoots = @('app', 'static', 'tests', 'scripts', 'deploy', 'docs', 'screenshots', '.github', 'migrations')
$allowedFiles = @('AGENTS.md', 'README.md', 'LICENSE', 'Dockerfile', 'compose.yaml', 'compose.test.yaml', 'compose.improvements.yaml', 'requirements.txt', 'requirements-dev.txt', 'requirements-runtime.lock', 'package.json', 'package-lock.json', '.env.example', '.gitignore', '.dockerignore', 'pytest.ini', 'pyproject.toml', 'Start-ATLAS.cmd')
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($partialPath, [IO.Compression.ZipArchiveMode]::Create)
$manifest = [Collections.Generic.List[string]]::new()
try {
    $candidates = foreach ($rootName in $allowedRoots) {
        $rootPath = Join-Path $projectRoot $rootName
        if (Test-Path -LiteralPath $rootPath -PathType Container) { Get-ChildItem -LiteralPath $rootPath -File -Recurse -Force }
    }
    $candidates += foreach ($fileName in $allowedFiles) {
        $filePath = Join-Path $projectRoot $fileName
        if (Test-Path -LiteralPath $filePath -PathType Leaf) { Get-Item -LiteralPath $filePath -Force }
    }
    $files = $candidates |
        Where-Object {
            $relativePath = $_.FullName.Substring($projectRoot.Length + 1).Replace([IO.Path]::DirectorySeparatorChar, [char]'/')
            $first = $relativePath.Split('/')[0]
            (($allowedRoots -contains $first) -or ($allowedFiles -contains $relativePath)) -and
            ($relativePath -notmatch '(^|/)(__pycache__|\.pytest_cache|node_modules|\.venv)(/|$)') -and
            ($_.Name -notmatch '(^\.env(\..*)?$|\.(db|sqlite|sqlite3|dump|pyc|pyo)$|\.(db|sqlite3)-(wal|shm|journal)$)')
        }
    # .env.example is the only permitted env file.
    $envExample = Get-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Force
    $files = @($files) + @($envExample)
    foreach ($file in ($files | Sort-Object FullName -Unique)) {
        $entryName = $file.FullName.Substring($projectRoot.Length + 1).Replace([IO.Path]::DirectorySeparatorChar, [char]'/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entryName, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
        $manifest.Add($entryName)
    }
} finally { $archive.Dispose() }
foreach ($required in @('app/main.py','app/db.py','app/config.py','app/improvements.py','app/improvement_db.py','static/app.js','static/campus.js','static/improvements.js','static/campus.css','app/learning.py','app/learning_db.py','app/services.py','app/services_db.py','app/campus.py','app/campus_db.py','static/style.css','static/usability.css','static/index.html','Dockerfile','compose.yaml','compose.test.yaml','compose.improvements.yaml','deploy/init-db.sh','deploy/Caddyfile','deploy/Caddyfile.test','scripts/improvement_deployment.py','scripts/improvement_runtime.py','requirements.txt','requirements-runtime.lock','package.json','package-lock.json','.env.example','README.md','Start-ATLAS.cmd')) {
    if (-not $manifest.Contains($required)) { throw "Incomplete archive: required file $required is missing. The partial file was not published." }
}
Move-Item -LiteralPath $partialPath -Destination $archivePath
$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText("$archivePath.sha256", "$hash  $([IO.Path]::GetFileName($archivePath))`n", $utf8)
[IO.File]::WriteAllLines("$archivePath.manifest.txt", $manifest, $utf8)
Write-Output "Source archive: $archivePath"
Write-Output "Files: $($manifest.Count)"
Write-Output "SHA256: $hash"
