$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$CanonicalName = 'XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip'
$CanonicalSha256 = '8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7'
$RequiredProbeVersion = 'R7_R1_R6_SOURCE_PROBE_V2'
$RequiredBundleVersion = 'R7_R1_R6_SOURCE_BUNDLE_V3'
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
    $probe = Get-Content -LiteralPath $ProbePath -Raw | ConvertFrom-Json

    if ($manifest.bundle_version -ne $RequiredBundleVersion) { Fail ('stale or unexpected bundle version: ' + [string]$manifest.bundle_version) }
    if ($manifest.canonical_parent_zip_sha256 -ne $CanonicalSha256) { Fail 'bundle parent hash mismatch' }
    if ($manifest.source_only_bundle -ne $true) { Fail 'bundle is not source-only' }
    if ($manifest.static_local_python_dependency_closure_extracted -ne $true) { Fail 'local Python dependency closure was not confirmed' }
    if ($manifest.required_local_imports_resolved -ne $true) { Fail 'required local imports were not resolved' }
    if ($manifest.dynamic_imports_allowed -ne $false) { Fail 'dynamic imports may not be admitted' }
    if ($manifest.strategy_executed -ne $false) { Fail 'bundle claims strategy execution' }
    if ($manifest.strategy_retuned -ne $false) { Fail 'bundle claims strategy retuning' }
    if ($manifest.final_holdout_accessed -ne $false) { Fail 'bundle claims Final Holdout access' }
    if ($manifest.producer_admitted -ne $false) { Fail 'source extraction may not admit producer' }

    $dependencyFiles = @($manifest.dependency_closure_files)
    $fileProperties = @($manifest.files.PSObject.Properties)
    if ($manifest.dependency_count -ne $dependencyFiles.Count) { Fail 'dependency_count does not match dependency_closure_files' }
    if ($dependencyFiles.Count -ne $fileProperties.Count) { Fail 'dependency closure and file hash map counts differ' }
    if ($dependencyFiles.Count -lt 3) { Fail 'dependency closure unexpectedly smaller than the frozen entry-source set' }
    if (($dependencyFiles | Select-Object -Unique).Count -ne $dependencyFiles.Count) { Fail 'dependency closure contains duplicate paths' }

    foreach ($relative in $dependencyFiles) {
        $rel = [string]$relative
        if (-not $rel.EndsWith('.py', [System.StringComparison]::OrdinalIgnoreCase)) { Fail ('non-Python file leaked into source closure: ' + $rel) }
        $normalized = $rel.Replace('\','/').ToLowerInvariant()
        if ($normalized.StartsWith('research_consumed_validation/') -or
            $normalized.Contains('/final_holdout') -or
            $normalized.StartsWith('final_holdout')) {
            Fail ('prohibited research/Holdout path entered source closure: ' + $rel)
        }
        $sourcePath = Join-Path $Output ($rel.Replace('/','\'))
        if (!(Test-Path -LiteralPath $sourcePath -PathType Leaf)) { Fail ('dependency file missing from extracted source bundle: ' + $rel) }
        $property = $manifest.files.PSObject.Properties[$rel]
        if ($null -eq $property) { Fail ('dependency file missing from manifest hash map: ' + $rel) }
        $expectedHash = [string]$property.Value.sha256
        $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($expectedHash -ne $actualHash) { Fail ('dependency file hash mismatch: ' + $rel) }
    }

    foreach ($relative in @('v16r6/engine.py','v16r5/engine.py','V16_R5_MAIN.py')) {
        if ($dependencyFiles -notcontains $relative) { Fail ('required source missing from dependency closure: ' + $relative) }
    }

    if ($probe.probe_version -ne $RequiredProbeVersion) { Fail ('stale or unexpected source probe version: ' + [string]$probe.probe_version) }
    if ($probe.normalized_ast_source_included -ne $true) { Fail 'source probe did not include normalized AST implementation source' }
    if ($probe.source_only_probe -ne $true -or $probe.strategy_executed -ne $false) { Fail 'source probe boundary invalid' }
    if ($probe.final_holdout_accessed -ne $false -or $probe.strategy_retuned -ne $false -or $probe.producer_admitted -ne $false) { Fail 'source probe constitutional boundary invalid' }

    $probeHash = (Get-FileHash -LiteralPath $ProbePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([string]$manifest.source_probe_sha256 -ne $probeHash) { Fail 'source probe hash is not bound to bundle manifest' }

    Write-Host ''
    Write-Host '[PASS] Canonical frozen R5/R6 producer source and local Python dependency closure extracted safely.' -ForegroundColor Green
    Write-Host ('Source bundle: ' + $Output)
    Write-Host ('Manifest: ' + $ManifestPath)
    Write-Host ('Implementation map: ' + $ProbePath)
    Write-Host ('Local source files: ' + $dependencyFiles.Count)
    if ($null -ne $manifest.unresolved_nonarchive_imports) {
        Write-Host 'Non-archive imports were recorded for explicit environment review; they were not treated as local source.' -ForegroundColor Yellow
    }
    Write-Host 'Execution remains hard-locked; extraction alone does not admit a producer.' -ForegroundColor Yellow
}
finally {
    if (Test-Path -LiteralPath $Work) {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
