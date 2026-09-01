$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$CanonicalName = 'XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip'
$CanonicalSha256 = '8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7'
$OutputName = 'XAU_BOUNDED_RECOVERY_V16_R7_R1_FULL_RUNTIME_REPAIR.zip'
$RequiredSourcePreflightVersion = 'R7_R1_CANONICAL_SOURCE_BUILD_PREFLIGHT_V2'
$RequiredSourceBundleVersion = 'R7_R1_R6_SOURCE_BUNDLE_V4'
$RequiredSourceProbeVersion = 'R7_R1_R6_SOURCE_PROBE_V2'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ParentZip = Join-Path $Here $CanonicalName
$OutputZip = Join-Path $Here $OutputName
$OutputSha = $OutputZip + '.sha256'
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ('XAU_R7_R1_' + [Guid]::NewGuid().ToString('N'))
$Extract = Join-Path $Work 'package'
$Verify = Join-Path $Work 'verify'
$SourcePreflight = Join-Path $Work 'canonical_source_preflight'

$ProtectedSuffixes = @(
    'v16r6/engine.py',
    'v16r5/engine.py',
    'V16_R5_MAIN.py',
    'V16_R6_RESEARCH_DESIGN_LOCK.json',
    'V16_R6_FINAL_HOLDOUT_PREREGISTRATION.json'
)

$OperatorToolCopies = @(
    [pscustomobject]@{ Source = 'PROBE_CANONICAL_R6_SOURCE.ps1'; Destination = 'PROBE_CANONICAL_R6_SOURCE.ps1' },
    [pscustomobject]@{ Source = 'EXTRACT_CANONICAL_R6_PRODUCER_SOURCE.ps1'; Destination = 'EXTRACT_CANONICAL_R6_PRODUCER_SOURCE.ps1' },
    [pscustomobject]@{ Source = 'SEAL_R6_PRODUCER_CANDIDATE.ps1'; Destination = 'SEAL_R6_PRODUCER_CANDIDATE.ps1' },
    [pscustomobject]@{ Source = 'PRECHECK_R6_FUSED_RELEASE.ps1'; Destination = 'PRECHECK_R6_FUSED_RELEASE.ps1' },
    [pscustomobject]@{ Source = 'PACKAGE_README.md'; Destination = 'R7_R1_PACKAGE_README.md' },
    [pscustomobject]@{ Source = 'REPAIR_AUDIT.md'; Destination = 'R7_R1_REPAIR_AUDIT.md' }
)
$PackagedOperatorFiles = @($OperatorToolCopies | ForEach-Object { [string]$_.Destination })

function Fail([string]$Message) { throw ('R7-R1 BUILD BLOCKED: ' + $Message) }
function Write-Utf8NoBom([string]$Path, [string]$Text) { [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false))) }
function Get-Rel([string]$Base, [string]$Path) { return $Path.Substring($Base.Length).TrimStart([char]'\',[char]'/').Replace('\','/') }

function Get-TreeHashes([string]$Root) {
    $map = [ordered]@{}
    Get-ChildItem -LiteralPath $Root -Recurse -File | Sort-Object FullName | ForEach-Object {
        $rel = Get-Rel $Root $_.FullName
        $map[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $map
}

function Get-ProtectedHashes([string]$Root) {
    $map = [ordered]@{}
    $all = Get-ChildItem -LiteralPath $Root -Recurse -File
    foreach ($suffix in $ProtectedSuffixes) {
        $matches = @($all | Where-Object { (Get-Rel $Root $_.FullName).EndsWith($suffix, [System.StringComparison]::OrdinalIgnoreCase) })
        if ($matches.Count -ne 1) { Fail ("protected path resolution failed for {0}: matches={1}" -f $suffix, $matches.Count) }
        $rel = Get-Rel $Root $matches[0].FullName
        $map[$rel] = (Get-FileHash -LiteralPath $matches[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $map
}

function Get-R7RuntimeCodeHashes([string]$Root) {
    $map = [ordered]@{}
    $runtimeRoot = Join-Path $Root 'r7_runtime'
    Get-ChildItem -LiteralPath $runtimeRoot -Recurse -File -Filter '*.py' | Sort-Object FullName | ForEach-Object {
        $rel = Get-Rel $Root $_.FullName
        $map[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $launcher = Join-Path $Root 'START_XAU.bat'
    if (!(Test-Path -LiteralPath $launcher -PathType Leaf)) { Fail 'R7-R1 START_XAU.bat missing' }
    $map['START_XAU.bat'] = (Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash.ToLowerInvariant()
    return $map
}

function Get-R7OperatorToolHashes([string]$Root) {
    $map = [ordered]@{}
    foreach ($rel in $PackagedOperatorFiles) {
        $path = Join-Path $Root ($rel.Replace('/','\'))
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { Fail ('packaged operator file missing: ' + $rel) }
        $map[$rel] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $map
}

function Get-MapEntries($Expected) {
    if ($Expected -is [System.Collections.IDictionary]) {
        return @($Expected.GetEnumerator() | ForEach-Object { [pscustomobject]@{ Key = [string]$_.Key; Value = [string]$_.Value } })
    }
    if ($null -ne $Expected -and $null -ne $Expected.PSObject) {
        return @($Expected.PSObject.Properties | ForEach-Object { [pscustomobject]@{ Key = [string]$_.Name; Value = [string]$_.Value } })
    }
    Fail 'expected hash map is neither IDictionary nor PSCustomObject'
}

function Verify-HashMap([string]$Root, $Expected, [string]$Label) {
    foreach ($entry in (Get-MapEntries $Expected)) {
        $rel = [string]$entry.Key
        $path = Join-Path $Root ($rel.Replace('/','\'))
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { Fail ($Label + ' file missing: ' + $rel) }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.Value) { Fail ($Label + ' hash mismatch: ' + $rel) }
    }
}

function Verify-InheritedTree([string]$Root, $Expected) {
    foreach ($entry in (Get-MapEntries $Expected)) {
        $rel = [string]$entry.Key
        if ($rel -ieq 'START_XAU.bat') { continue }
        $path = Join-Path $Root ($rel.Replace('/','\'))
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { Fail ('inherited parent file missing: ' + $rel) }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.Value) { Fail ('inherited parent file changed: ' + $rel) }
    }
}

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

function Invoke-PythonCapture($Python, [string[]]$Arguments) {
    $allArgs = @(); $allArgs += @($Python.Prefix); $allArgs += @($Arguments)
    $output = & $Python.Exe @allArgs 2>&1
    if ($LASTEXITCODE -ne 0) { Fail ('Python command failed: ' + ($Arguments -join ' ') + "`n" + ($output -join "`n")) }
    return @($output)
}

function Assert-PythonVersion($Python) {
    $out = Invoke-PythonCapture $Python @('-c','import sys; print("%d.%d.%d" % sys.version_info[:3]); raise SystemExit(0 if sys.version_info >= (3,9) else 9)')
    if ($out.Count -lt 1) { Fail 'unable to determine Python version' }
    Write-Host ('Python: ' + [string]$out[-1])
}

if (!(Test-Path -LiteralPath $ParentZip -PathType Leaf)) { Fail ("put {0} beside BUILD_R7_R1.ps1" -f $CanonicalName) }
$parentHash = (Get-FileHash -LiteralPath $ParentZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($parentHash -ne $CanonicalSha256) { Fail ("canonical R6 SHA-256 mismatch. expected={0} actual={1}" -f $CanonicalSha256, $parentHash) }

$Python = Find-Python
Assert-PythonVersion $Python
New-Item -ItemType Directory -Path $Extract -Force | Out-Null
New-Item -ItemType Directory -Path $Verify -Force | Out-Null

try {
    Expand-Archive -LiteralPath $ParentZip -DestinationPath $Extract -Force
    $parentTree = Get-TreeHashes $Extract
    $protected = Get-ProtectedHashes $Extract
    if (!$parentTree.Contains('START_XAU.bat')) { Fail 'canonical parent START_XAU.bat is missing' }
    $originalLauncherHash = [string]$parentTree['START_XAU.bat']

    $RuntimeTarget = Join-Path $Extract 'r7_runtime'
    $TestsTarget = Join-Path $Extract 'r7_runtime_tests'
    $FrozenParent = Join-Path $RuntimeTarget 'frozen_parent'
    New-Item -ItemType Directory -Path $RuntimeTarget -Force | Out-Null
    New-Item -ItemType Directory -Path $TestsTarget -Force | Out-Null
    New-Item -ItemType Directory -Path $FrozenParent -Force | Out-Null

    Copy-Item -LiteralPath (Join-Path $Extract 'START_XAU.bat') -Destination (Join-Path $FrozenParent 'START_XAU_R6_ORIGINAL.bat.txt') -Force
    Copy-Item -Path (Join-Path $Here 'runtime\*') -Destination $RuntimeTarget -Recurse -Force
    Copy-Item -Path (Join-Path $Here 'tests\*') -Destination $TestsTarget -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $Here 'R7_R1_RUNTIME_CONFIG.json') -Destination (Join-Path $Extract 'R7_R1_RUNTIME_CONFIG.json') -Force
    Copy-Item -LiteralPath (Join-Path $Here 'START_XAU_R7_R1.bat.template') -Destination (Join-Path $Extract 'START_XAU.bat') -Force

    foreach ($copy in $OperatorToolCopies) {
        $source = Join-Path $Here ([string]$copy.Source)
        $destinationRel = [string]$copy.Destination
        if (!(Test-Path -LiteralPath $source -PathType Leaf)) { Fail ('operator source file missing: ' + [string]$copy.Source) }
        if ($parentTree.Keys -contains $destinationRel) { Fail ('operator destination conflicts with inherited R6 file: ' + $destinationRel) }
        Copy-Item -LiteralPath $source -Destination (Join-Path $Extract $destinationRel) -Force
    }

    Verify-InheritedTree $Extract $parentTree
    $protectedAfter = Get-ProtectedHashes $Extract
    foreach ($entry in (Get-MapEntries $protected)) {
        if ([string]$protectedAfter[$entry.Key] -ne [string]$entry.Value) { Fail ('protected R6 strategy/policy file changed: ' + [string]$entry.Key) }
    }
    $frozenLauncherHash = (Get-FileHash -LiteralPath (Join-Path $FrozenParent 'START_XAU_R6_ORIGINAL.bat.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($frozenLauncherHash -ne $originalLauncherHash) { Fail 'preserved R6 launcher bytes do not match original launcher hash' }

    Push-Location $Extract
    try {
        $sourcePreflightRaw = Invoke-PythonCapture $Python @('-m','r7_runtime.r6_build_source_preflight','--zip',$ParentZip,'--output',$SourcePreflight)
    }
    finally { Pop-Location }
    try {
        $sourcePreflightResult = (($sourcePreflightRaw -join "`n") | ConvertFrom-Json)
    }
    catch { Fail ('canonical source preflight returned invalid JSON: ' + $_.Exception.Message) }
    if ([string]$sourcePreflightResult.preflight_version -ne $RequiredSourcePreflightVersion) { Fail 'canonical source preflight version mismatch' }
    if ([string]$sourcePreflightResult.bundle_version -ne $RequiredSourceBundleVersion) { Fail 'canonical source bundle version mismatch' }
    if ([string]$sourcePreflightResult.source_probe_version -ne $RequiredSourceProbeVersion) { Fail 'canonical source probe version mismatch' }
    if ([string]$sourcePreflightResult.canonical_parent_zip_sha256 -ne $CanonicalSha256) { Fail 'canonical source preflight parent SHA mismatch' }
    if ($sourcePreflightResult.source_only_bundle_verified -ne $true) { Fail 'canonical source preflight did not prove source-only extraction' }
    if ($sourcePreflightResult.dependency_closure_verified -ne $true) { Fail 'canonical source preflight did not prove dependency closure' }
    if ($sourcePreflightResult.required_engine_contract_verified -ne $true) { Fail 'canonical source preflight did not prove frozen engine contract' }
    if ($sourcePreflightResult.prohibited_source_paths_blocked -ne $true) { Fail 'canonical source preflight did not prove prohibited source-path blocking' }
    if ($sourcePreflightResult.owned_output_replacement_verified -ne $true) { Fail 'canonical source preflight did not prove owned-output-only replacement' }
    if ([string]$sourcePreflightResult.ownership_marker_sha256 -notmatch '^[0-9a-fA-F]{64}$') { Fail 'canonical source preflight ownership marker hash invalid' }
    if ($sourcePreflightResult.strategy_executed -ne $false) { Fail 'canonical source preflight unexpectedly executed strategy logic' }
    if ($sourcePreflightResult.strategy_retuned -ne $false) { Fail 'canonical source preflight reports strategy retuning' }
    if ($sourcePreflightResult.final_holdout_accessed -ne $false) { Fail 'canonical source preflight reports Final Holdout access' }
    if ($sourcePreflightResult.producer_admitted -ne $false) { Fail 'canonical source preflight unexpectedly admitted producer' }

    $r7RuntimeHashes = Get-R7RuntimeCodeHashes $Extract
    $r7OperatorHashes = Get-R7OperatorToolHashes $Extract
    $manifest = [ordered]@{
        version = 'V16_R7_R1_FULL_RUNTIME_REPAIR'
        canonical_parent_zip = $CanonicalName
        canonical_parent_zip_sha256 = $CanonicalSha256
        build_verified_parent_zip_sha256 = $parentHash
        parent_tree_sha256 = $parentTree
        protected_r6_hashes = $protected
        r7_runtime_code_sha256 = $r7RuntimeHashes
        r7_operator_tool_sha256 = $r7OperatorHashes
        original_start_xau_sha256 = $originalLauncherHash
        allowed_inherited_change = @('START_XAU.bat')
        final_holdout_accessed = $false
        strategy_retuned = $false
        demo_only = $true
        execution_enabled_by_default = $false
        causal_r6_producer_ready = $false
    }
    Write-Utf8NoBom (Join-Path $Extract 'R7_R1_PARENT_INTEGRITY.json') ($manifest | ConvertTo-Json -Depth 12)

    Push-Location $Extract
    try {
        Invoke-Python $Python @('-m','compileall','-q','r7_runtime','r7_runtime_tests')
        Invoke-Python $Python @('-m','unittest','discover','-s','r7_runtime_tests','-v')
        $offline = Invoke-PythonCapture $Python @('-m','r7_runtime.runtime','--offline-status')
    }
    finally { Pop-Location }

    $verification = [ordered]@{
        version = 'V16_R7_R1_FULL_RUNTIME_REPAIR'
        parent_zip_sha256 = $parentHash
        parent_zip_verified = $true
        inherited_parent_files_verified = $true
        protected_r6_files_verified = $true
        r7_runtime_code_verified = $true
        r7_operator_tools_verified = $true
        original_launcher_preserved = $true
        canonical_source_preflight_pass = $true
        canonical_source_preflight_version = [string]$sourcePreflightResult.preflight_version
        canonical_source_bundle_version = [string]$sourcePreflightResult.bundle_version
        canonical_source_probe_version = [string]$sourcePreflightResult.source_probe_version
        source_prohibited_paths_blocked = $true
        source_owned_output_replacement_verified = $true
        canonical_source_preflight = $sourcePreflightResult
        python_compile_pass = $true
        unit_tests_pass = $true
        offline_runtime_integrity_pass = $true
        causal_r6_producer_ready = $false
        execution_runtime_hard_locked = $true
        offline_runtime_output = ($offline -join "`n")
        final_holdout_accessed = $false
        strategy_retuned = $false
    }
    Write-Utf8NoBom (Join-Path $Extract 'R7_R1_BUILD_VERIFICATION.json') ($verification | ConvertTo-Json -Depth 12)

    $stateDir = Join-Path $Extract 'r7_runtime_state'
    if (Test-Path -LiteralPath $stateDir) { Remove-Item -LiteralPath $stateDir -Recurse -Force }
    Get-ChildItem -LiteralPath $Extract -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $Extract -Recurse -File -Filter '*.pyc' -ErrorAction SilentlyContinue | Remove-Item -Force

    if (Test-Path -LiteralPath $OutputZip) { Remove-Item -LiteralPath $OutputZip -Force }
    if (Test-Path -LiteralPath $OutputSha) { Remove-Item -LiteralPath $OutputSha -Force }
    Compress-Archive -Path (Join-Path $Extract '*') -DestinationPath $OutputZip -CompressionLevel Optimal

    Expand-Archive -LiteralPath $OutputZip -DestinationPath $Verify -Force
    $verifyManifest = Get-Content -LiteralPath (Join-Path $Verify 'R7_R1_PARENT_INTEGRITY.json') -Raw | ConvertFrom-Json
    if ($verifyManifest.causal_r6_producer_ready -ne $false) { Fail 'extracted ZIP incorrectly claims causal R6 producer readiness' }
    Verify-InheritedTree $Verify $verifyManifest.parent_tree_sha256
    $verifyProtected = Get-ProtectedHashes $Verify
    foreach ($prop in $verifyManifest.protected_r6_hashes.PSObject.Properties) {
        if ([string]$verifyProtected[$prop.Name] -ne [string]$prop.Value) { Fail ('extracted ZIP protected hash mismatch: ' + $prop.Name) }
    }
    Verify-HashMap $Verify $verifyManifest.r7_runtime_code_sha256 'extracted R7 runtime'
    Verify-HashMap $Verify $verifyManifest.r7_operator_tool_sha256 'extracted R7 operator tool'
    $verifyFrozenHash = (Get-FileHash -LiteralPath (Join-Path $Verify 'r7_runtime\frozen_parent\START_XAU_R6_ORIGINAL.bat.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($verifyFrozenHash -ne [string]$verifyManifest.original_start_xau_sha256) { Fail 'extracted ZIP frozen launcher hash mismatch' }
    $verifyBuild = Get-Content -LiteralPath (Join-Path $Verify 'R7_R1_BUILD_VERIFICATION.json') -Raw | ConvertFrom-Json
    if ($verifyBuild.canonical_source_preflight_pass -ne $true) { Fail 'extracted ZIP lacks canonical source preflight PASS evidence' }
    if ([string]$verifyBuild.canonical_source_preflight_version -ne $RequiredSourcePreflightVersion) { Fail 'extracted ZIP source preflight version mismatch' }
    if ([string]$verifyBuild.canonical_source_bundle_version -ne $RequiredSourceBundleVersion) { Fail 'extracted ZIP source bundle version mismatch' }
    if ([string]$verifyBuild.canonical_source_probe_version -ne $RequiredSourceProbeVersion) { Fail 'extracted ZIP source probe version mismatch' }
    if ([string]$verifyBuild.canonical_source_preflight.preflight_version -ne $RequiredSourcePreflightVersion) { Fail 'extracted ZIP nested source preflight version mismatch' }
    if ([string]$verifyBuild.canonical_source_preflight.bundle_version -ne $RequiredSourceBundleVersion) { Fail 'extracted ZIP nested source bundle version mismatch' }
    if ([string]$verifyBuild.canonical_source_preflight.source_probe_version -ne $RequiredSourceProbeVersion) { Fail 'extracted ZIP nested source probe version mismatch' }
    if ([string]$verifyBuild.canonical_source_preflight.canonical_parent_zip_sha256 -ne $CanonicalSha256) { Fail 'extracted ZIP source preflight parent SHA mismatch' }
    if ($verifyBuild.source_prohibited_paths_blocked -ne $true -or $verifyBuild.canonical_source_preflight.prohibited_source_paths_blocked -ne $true) { Fail 'extracted ZIP source preflight lacks prohibited-path blocking proof' }
    if ($verifyBuild.source_owned_output_replacement_verified -ne $true -or $verifyBuild.canonical_source_preflight.owned_output_replacement_verified -ne $true) { Fail 'extracted ZIP source preflight lacks owned-output replacement proof' }
    if ([string]$verifyBuild.canonical_source_preflight.ownership_marker_sha256 -notmatch '^[0-9a-fA-F]{64}$') { Fail 'extracted ZIP source preflight ownership marker hash invalid' }
    if ($verifyBuild.canonical_source_preflight.final_holdout_accessed -ne $false) { Fail 'extracted ZIP source preflight reports Final Holdout access' }
    if ($verifyBuild.canonical_source_preflight.strategy_retuned -ne $false) { Fail 'extracted ZIP source preflight reports strategy retuning' }

    Push-Location $Verify
    try {
        Invoke-Python $Python @('-m','compileall','-q','r7_runtime','r7_runtime_tests')
        Invoke-Python $Python @('-m','unittest','discover','-s','r7_runtime_tests','-v')
        Invoke-Python $Python @('-m','r7_runtime.runtime','--offline-status')
    }
    finally { Pop-Location }

    $finalHash = (Get-FileHash -LiteralPath $OutputZip -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath $OutputSha -Value ("{0}  {1}" -f $finalHash, $OutputName) -Encoding ASCII
    Write-Host ''
    Write-Host '[PASS] R7-R1 full repair package created and clean-extraction verified.' -ForegroundColor Green
    Write-Host ('File: ' + $OutputZip)
    Write-Host ('SHA-256: ' + $finalHash)
}
finally {
    if (Test-Path -LiteralPath $Work) { Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue }
}
