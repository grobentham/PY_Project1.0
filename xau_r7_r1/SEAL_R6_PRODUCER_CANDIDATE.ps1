param(
    [Parameter(Mandatory=$true)]
    [string]$RuntimeRoot,

    [Parameter(Mandatory=$true)]
    [string]$CandidateRoot,

    [string]$Output = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ('XAU_R6_PRODUCER_SEAL_' + [Guid]::NewGuid().ToString('N'))
$RuntimeStage = Join-Path $Work 'r7_runtime'
$RequiredSealVersion = 'R7_R1_R6_PRODUCER_CANDIDATE_SEAL_V4'
$RequiredSourceBundleVersion = 'R7_R1_R6_SOURCE_BUNDLE_V4'
$RequiredReplayVersion = 'R7_R1_R6_PRODUCER_REPLAY_V4'
$RequiredSourcePolicyVersion = 'R7_R1_R6_PRODUCER_SOURCE_POLICY_V4'

function Fail([string]$Message) { throw ('R6 PRODUCER SEAL BLOCKED: ' + $Message) }

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

function Resolve-RuntimeToolSource {
    $Dev = Join-Path $Here 'runtime'
    if (Test-Path -LiteralPath $Dev -PathType Container) { return $Dev }
    $Packaged = Join-Path $Here 'r7_runtime'
    if (Test-Path -LiteralPath $Packaged -PathType Container) { return $Packaged }
    Fail 'R7 runtime tool source not found. Expected runtime\ or r7_runtime\ beside this script.'
}

function Assert-PackagedSelfIntegrity($Python) {
    $Manifest = Join-Path $Here 'R7_R1_PARENT_INTEGRITY.json'
    if (!(Test-Path -LiteralPath $Manifest -PathType Leaf)) { return }
    Push-Location $Here
    try {
        Invoke-Python $Python @(
            '-c',
            'from pathlib import Path; from r7_runtime.r6_integrity import verify_runtime_package_integrity; verify_runtime_package_integrity(Path.cwd())'
        )
    }
    finally { Pop-Location }
}

function Assert-SourceSecurityContracts($SealObject) {
    if ($SealObject.source_bundle_security_contract_pass -ne $true) { Fail 'candidate seal did not prove source-bundle security contract' }
    $source = $SealObject.source_bundle_security_contract
    if ($null -eq $source) { Fail 'candidate seal missing source-bundle security contract' }
    if ([string]$source.bundle_version -ne $RequiredSourceBundleVersion) { Fail 'candidate seal source-bundle version mismatch' }
    foreach ($field in @('static_dependency_closure_recomputed','dynamic_import_policy_recomputed','prohibited_source_paths_blocked','owned_output_replacement_only')) {
        if ($source.$field -ne $true) { Fail ('candidate seal source-bundle guard not proven: ' + $field) }
    }
    $markerHash = [string]$source.ownership_marker_sha256
    if ($markerHash.Length -ne 64 -or $markerHash -notmatch '^[0-9a-fA-F]{64}$') { Fail 'candidate seal source ownership marker SHA-256 invalid' }

    if ($SealObject.reference_source_security_contract_pass -ne $true) { Fail 'candidate seal did not prove reference source security contract' }
    $reference = $SealObject.reference_source_security_contract
    if ($null -eq $reference) { Fail 'candidate seal missing reference source security contract' }
    if ([string]$reference.source_bundle_version -ne $RequiredSourceBundleVersion) { Fail 'candidate seal reference source-bundle version mismatch' }
    foreach ($field in @('source_bundle_static_closure_recomputed','source_bundle_dynamic_import_policy_recomputed','source_bundle_prohibited_paths_blocked','reference_generated_by_exact_canonical_source_executor')) {
        if ($reference.$field -ne $true) { Fail ('candidate seal reference-source guard not proven: ' + $field) }
    }
}

function Assert-ReplaySecurityContract($SealObject) {
    if ($SealObject.trusted_replay_security_contract_pass -ne $true) { Fail 'candidate seal did not prove replay security contract' }
    $contract = $SealObject.trusted_replay_security_contract
    if ($null -eq $contract) { Fail 'candidate seal missing replay security contract' }
    if ([string]$contract.replay_version -ne $RequiredReplayVersion) { Fail 'candidate seal replay version mismatch' }
    if ([string]$contract.source_policy_version -ne $RequiredSourcePolicyVersion) { Fail 'candidate seal source-policy version mismatch' }
    if ($contract.process_isolation_enforced -ne $true) { Fail 'candidate seal did not prove replay process isolation' }
    $workerHash = [string]$contract.worker_module_sha256
    if ($workerHash.Length -ne 64 -or $workerHash -notmatch '^[0-9a-fA-F]{64}$') { Fail 'candidate seal replay worker SHA-256 invalid' }
    $wallTimeout = [double]$contract.wall_timeout_seconds
    if ($wallTimeout -le 0) { Fail 'candidate seal replay wall timeout invalid' }
    foreach ($field in @('max_fixture_count','max_input_depth','max_input_nodes_per_fixture','max_range_items','max_execution_line_events')) {
        $value = [long]$contract.$field
        if ($value -le 0) { Fail ('candidate seal replay resource limit invalid: ' + $field) }
    }
}

$RuntimeRoot = (Resolve-Path -LiteralPath $RuntimeRoot).Path
$CandidateRoot = (Resolve-Path -LiteralPath $CandidateRoot).Path
if (!(Test-Path -LiteralPath $RuntimeRoot -PathType Container)) { Fail 'RuntimeRoot must be an extracted R7-R1 runtime directory' }
if (!(Test-Path -LiteralPath $CandidateRoot -PathType Container)) { Fail 'CandidateRoot must be a producer candidate directory' }
if (!(Test-Path -LiteralPath (Join-Path $RuntimeRoot 'R7_R1_PARENT_INTEGRITY.json') -PathType Leaf)) {
    Fail 'RuntimeRoot does not contain R7_R1_PARENT_INTEGRITY.json'
}
if ($Output -eq '') {
    $Output = Join-Path $CandidateRoot 'R7_R1_R6_PRODUCER_CANDIDATE_SEAL.json'
}
elseif (-not [System.IO.Path]::IsPathRooted($Output)) {
    $Output = Join-Path (Get-Location).Path $Output
}

$Python = Find-Python
$RuntimeSource = Resolve-RuntimeToolSource
Assert-PackagedSelfIntegrity $Python
New-Item -ItemType Directory -Path $RuntimeStage -Force | Out-Null

try {
    Copy-Item -Path (Join-Path $RuntimeSource '*') -Destination $RuntimeStage -Recurse -Force
    Push-Location $Work
    try {
        Invoke-Python $Python @(
            '-m','r7_runtime.r6_producer_seal',
            '--runtime-root',$RuntimeRoot,
            '--candidate-root',$CandidateRoot,
            '--output',$Output
        )
    }
    finally {
        Pop-Location
    }

    if (!(Test-Path -LiteralPath $Output -PathType Leaf)) { Fail 'candidate seal was not generated' }
    $seal = Get-Content -LiteralPath $Output -Raw | ConvertFrom-Json
    if ($seal.seal_version -ne $RequiredSealVersion) { Fail 'unexpected candidate seal version' }
    if ($seal.admission_ready -ne $true) { Fail 'candidate seal did not prove admission readiness' }
    Assert-SourceSecurityContracts $seal
    Assert-ReplaySecurityContract $seal
    if ($seal.canonical_reference_replay_pass -ne $true) { Fail 'candidate seal did not prove canonical-reference replay authority' }
    if ([string]::IsNullOrWhiteSpace([string]$seal.authority_version)) { Fail 'candidate seal missing authority_version' }
    if ($seal.trusted_producer_replay_pass -ne $true) { Fail 'candidate seal did not prove trusted producer replay' }
    if ($seal.producer_source_policy_pass -ne $true) { Fail 'candidate seal did not prove producer source policy' }
    foreach ($field in @(
        'fixture_corpus_sha256',
        'producer_replay_attestation_sha256',
        'reference_stream_sha256',
        'reference_replay_attestation_sha256',
        'producer_stream_sha256'
    )) {
        $value = [string]$seal.$field
        if ($value.Length -ne 64 -or $value -notmatch '^[0-9a-fA-F]{64}$') { Fail ('candidate seal missing valid ' + $field) }
    }
    if ($seal.baseline_mutated -ne $false) { Fail 'candidate seal reports baseline mutation' }
    if ($seal.execution_unlocked -ne $false) { Fail 'candidate sealing may not unlock execution' }
    if ($seal.final_holdout_accessed -ne $false) { Fail 'candidate seal reports Final Holdout access' }
    if ($seal.strategy_retuned -ne $false) { Fail 'candidate seal reports strategy retuning' }

    Write-Host ''
    Write-Host '[PASS] R6 causal-producer V4 candidate sealed after V5 source provenance, canonical-reference authority and isolated replay-security verification.' -ForegroundColor Green
    Write-Host ('Seal: ' + $Output)
    Write-Host 'The baseline runtime was not modified and execution remains locked.' -ForegroundColor Yellow
}
finally {
    if (Test-Path -LiteralPath $Work) {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
