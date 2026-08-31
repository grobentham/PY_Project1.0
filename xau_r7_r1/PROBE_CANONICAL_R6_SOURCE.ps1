$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$CanonicalName = 'XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip'
$CanonicalSha256 = '8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7'
$RequiredProbeVersion = 'R7_R1_R6_SOURCE_PROBE_V2'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ParentZip = Join-Path $Here $CanonicalName
$Output = Join-Path $Here 'R7_R1_R6_SOURCE_PROBE.json'
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ('XAU_R6_SOURCE_PROBE_' + [Guid]::NewGuid().ToString('N'))
$Extract = Join-Path $Work 'r6'

function Fail([string]$Message) { throw ('R6 SOURCE PROBE BLOCKED: ' + $Message) }

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
New-Item -ItemType Directory -Path $Extract -Force | Out-Null

try {
    Expand-Archive -LiteralPath $ParentZip -DestinationPath $Extract -Force

    foreach ($relative in @('v16r6\engine.py','v16r5\engine.py','V16_R5_MAIN.py')) {
        if (!(Test-Path -LiteralPath (Join-Path $Extract $relative) -PathType Leaf)) {
            Fail ('required frozen source missing: ' + $relative)
        }
    }

    $RuntimeTarget = Join-Path $Extract 'r7_runtime'
    New-Item -ItemType Directory -Path $RuntimeTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $Here 'runtime\*') -Destination $RuntimeTarget -Recurse -Force

    Push-Location $Extract
    try {
        Invoke-Python $Python @('-m','r7_runtime.r6_source_probe','--root','.', '--output','R7_R1_R6_SOURCE_PROBE.json')
    }
    finally {
        Pop-Location
    }

    $Generated = Join-Path $Extract 'R7_R1_R6_SOURCE_PROBE.json'
    if (!(Test-Path -LiteralPath $Generated -PathType Leaf)) { Fail 'source-probe report was not generated' }
    $report = Get-Content -LiteralPath $Generated -Raw | ConvertFrom-Json
    if ($report.probe_version -ne $RequiredProbeVersion) { Fail ('stale or unexpected probe version: ' + [string]$report.probe_version) }
    if ($report.canonical_parent_zip_sha256 -ne $CanonicalSha256) { Fail 'probe report canonical hash mismatch' }
    if ($report.source_only_probe -ne $true) { Fail 'probe was not source-only' }
    if ($report.normalized_ast_source_included -ne $true) { Fail 'probe did not include normalized AST implementation source' }
    if ($report.strategy_executed -ne $false) { Fail 'probe claims strategy execution' }
    if ($report.final_holdout_accessed -ne $false) { Fail 'probe claims Final Holdout access' }
    if ($report.producer_admitted -ne $false) { Fail 'probe may not admit producer by itself' }
    if ($report.required_engine_contract_present -ne $true) { Fail 'frozen engine contract was not confirmed' }

    Copy-Item -LiteralPath $Generated -Destination $Output -Force
    Write-Host '[PASS] Exact frozen R5/R6 source implementation mapped without strategy execution.' -ForegroundColor Green
    Write-Host ('Report: ' + $Output)
}
finally {
    if (Test-Path -LiteralPath $Work) {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
