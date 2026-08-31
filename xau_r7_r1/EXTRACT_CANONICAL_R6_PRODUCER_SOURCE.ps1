$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$CanonicalName = 'XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip'
$CanonicalSha256 = '8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ParentZip = Join-Path $Here $CanonicalName
$Output = Join-Path $Here 'R7_R1_R6_PRODUCER_SOURCE'
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ('XAU_R6_SOURCE_BUNDLE_' + [Guid]::NewGuid().ToString('N'))
$RuntimeStage = Join-Path $Work 'r7_runtime'

function Fail([string]$Message) { throw ('R6 SOURCE EXTRACTION BLOCKED: ' + $Message) }

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) { return @{ Exe = 'py'; Prefix = @('-3') } }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @{ Exe = 'python'; Prefix = @() } }
    Fail 'Python 3 was not found on PATH'
}

function Invoke-Python($Python, [string[]]$Arguments) {
    $allArgs = @(); $allArgs += @($Python.Prefix); $allArgs += @($Arguments)
    & $Python.Exe @allArgs
    if ($LASTEXITCODE -ne 0) { Fail ('Python command failed: ' + ($Arguments -join ' ')) }
}

if (!(Test-Path -LiteralPath $ParentZip -PathType Leaf)) {
    Fail ("put {0} beside this script" -f $CanonicalName)
}

$actual = (Get-FileHash -LiteralPath $ParentZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $CanonicalSha256) {
    Fail ("canonical R6 SHA-256 mismatch. expected={0} actual={1}" -f $CanonicalSha256, $actual)
}

$Python = Find-Python
New-Item -ItemType Directory -Path $RuntimeStage -Force | Out-Null

try {
    Copy-Item -Path (Join-Path $Here 'runtime\*') -Destination $RuntimeStage -Recurse -Force
    Push-Location $Work
    try {
        Invoke-Python $Python @(
            '-m','r7_runtime.r6_source_bundle',
            '--zip',$ParentZip,
            '--output',$Output
        )
    }
    finally {
        Pop-Location
    }

    $ManifestPath = Join-Path $Output 'R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json'
    $ProbePath = Join-Path $Output 'R7_R1_R6_SOURCE_PROBE.json'
    if (!(Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { Fail 'bundle manifest missing' }
    if (!(Test-Path -LiteralPath $ProbePath -PathType Leaf)) { Fail 'source probe missing' }

    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ($manifest.canonical_parent_zip_sha256 -ne $CanonicalSha256) { Fail 'bundle parent hash mismatch' }
    if ($manifest.source_only_bundle -ne $true) { Fail 'bundle is not source-only' }
    if ($manifest.strategy_executed -ne $false) { Fail 'bundle claims strategy execution' }
    if ($manifest.strategy_retuned -ne $false) { Fail 'bundle claims strategy retuning' }
    if ($manifest.final_holdout_accessed -ne $false) { Fail 'bundle claims Final Holdout access' }
    if ($manifest.producer_admitted -ne $false) { Fail 'source extraction may not admit producer' }

    foreach ($relative in @('v16r6\engine.py','v16r5\engine.py','V16_R5_MAIN.py')) {
        if (!(Test-Path -LiteralPath (Join-Path $Output $relative) -PathType Leaf)) {
            Fail ('required source missing from bundle: ' + $relative)
        }
    }
    if (Test-Path -LiteralPath (Join-Path $Output 'research_consumed_validation')) {
        Fail 'research/validation data leaked into producer source bundle'
    }

    Write-Host ''
    Write-Host '[PASS] Canonical frozen R5/R6 producer source extracted safely.' -ForegroundColor Green
    Write-Host ('Source bundle: ' + $Output)
    Write-Host ('Manifest: ' + $ManifestPath)
    Write-Host 'Execution remains hard-locked; extraction alone does not admit a producer.' -ForegroundColor Yellow
}
finally {
    if (Test-Path -LiteralPath $Work) {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
