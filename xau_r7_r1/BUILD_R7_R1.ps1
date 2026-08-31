$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$CanonicalName = 'XAU_BOUNDED_RECOVERY_V16_PROFIT_TRANSFER_R6_RESEARCH_FROZEN.zip'
$CanonicalSha256 = '8b54c6bc53c38c34b8e88d39893687e8ba75b063897c8b097aaedc68d614fca7'
$OutputName = 'XAU_BOUNDED_RECOVERY_V16_R7_R1_FULL_RUNTIME_REPAIR.zip'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ParentZip = Join-Path $Here $CanonicalName
$OutputZip = Join-Path $Here $OutputName
$OutputSha = $OutputZip + '.sha256'
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ('XAU_R7_R1_' + [Guid]::NewGuid().ToString('N'))
$Extract = Join-Path $Work 'package'
$Verify = Join-Path $Work 'verify'

$ProtectedSuffixes = @(
    'v16r6/engine.py',
    'v16r5/engine.py',
    'V16_R5_MAIN.py',
    'V16_R6_RESEARCH_DESIGN_LOCK.json',
    'V16_R6_FINAL_HOLDOUT_PREREGISTRATION.json'
)

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

    Verify-InheritedTree $Extract $parentTree
    $protectedAfter = Get-ProtectedHashes $Extract
    foreach ($entry in (Get-MapEntries $protected)) {
        if ([string]$protectedAfter[$entry.Key] -ne [string]$entry.Value) { Fail ('protected R6 strategy/policy file changed: ' + [string]$entry.Key) }
    }
    $frozenLauncherHash = (Get-FileHash -LiteralPath (Join-Path $FrozenParent 'START_XAU_R6_ORIGINAL.bat.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($frozenLauncherHash -ne $originalLauncherHash) { Fail 'preserved R6 launcher bytes do not match original launcher hash' }

    $r7RuntimeHashes = Get-R7RuntimeCodeHashes $Extract
    $manifest = [ordered]@{
        version = 'V16_R7_R1_FULL_RUNTIME_REPAIR'
        canonical_parent_zip = $CanonicalName
        canonical_parent_zip_sha256 = $CanonicalSha256
        build_verified_parent_zip_sha256 = $parentHash
        parent_tree_sha256 = $parentTree
        protected_r6_hashes = $protected
        r7_runtime_code_sha256 = $r7RuntimeHashes
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
        original_launcher_preserved = $true
        python_compile_pass = $true
        unit_tests_pass = $true
        offline_runtime_integrity_pass = $true
        causal_r6_producer_ready = $false
        execution_runtime_hard_locked = $true
        offline_runtime_output = ($offline -join "`n")
        final_holdout_accessed = $false
        strategy_retuned = $false
    }
    Write-Utf8NoBom (Join-Path $Extract 'R7_R1_BUILD_VERIFICATION.json') ($verification | ConvertTo-Json -Depth 8)

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
    $verifyFrozenHash = (Get-FileHash -LiteralPath (Join-Path $Verify 'r7_runtime\frozen_parent\START_XAU_R6_ORIGINAL.bat.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($verifyFrozenHash -ne [string]$verifyManifest.original_start_xau_sha256) { Fail 'extracted ZIP frozen launcher hash mismatch' }

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
