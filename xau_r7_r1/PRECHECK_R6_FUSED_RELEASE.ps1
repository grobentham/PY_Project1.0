param(
    [Parameter(Mandatory=$true)]
    [string]$RuntimeRoot,

    [Parameter(Mandatory=$true)]
    [string]$CandidateRoot,

    [string]$Seal = '',

    [string]$Output = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ('XAU_R6_FUSED_PRECHECK_' + [Guid]::NewGuid().ToString('N'))
$RuntimeStage = Join-Path $Work 'r7_runtime'
$RequiredPrecheckVersion = 'R7_R1_R6_FUSED_RELEASE_PRECHECK_V3'

function Fail([string]$Message) { throw ('R6 FUSED RELEASE PRECHECK BLOCKED: ' + $Message) }

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

$RuntimeRoot = (Resolve-Path -LiteralPath $RuntimeRoot).Path
$CandidateRoot = (Resolve-Path -LiteralPath $CandidateRoot).Path
if (!(Test-Path -LiteralPath $RuntimeRoot -PathType Container)) { Fail 'RuntimeRoot must be an extracted R7-R1 runtime directory' }
if (!(Test-Path -LiteralPath $CandidateRoot -PathType Container)) { Fail 'CandidateRoot must be a sealed producer candidate directory' }

if ($Seal -eq '') {
    $Seal = Join-Path $CandidateRoot 'R7_R1_R6_PRODUCER_CANDIDATE_SEAL.json'
}
elseif (-not [System.IO.Path]::IsPathRooted($Seal)) {
    $Seal = Join-Path (Get-Location).Path $Seal
}
if (!(Test-Path -LiteralPath $Seal -PathType Leaf)) { Fail 'producer candidate seal is missing' }
$Seal = (Resolve-Path -LiteralPath $Seal).Path

if ($Output -eq '') {
    $Output = Join-Path $Here 'R7_R1_R6_FUSED_RELEASE_PRECHECK.json'
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
            '-m','r7_runtime.r6_fused_release_precheck',
            '--runtime-root',$RuntimeRoot,
            '--candidate-root',$CandidateRoot,
            '--seal',$Seal,
            '--output',$Output
        )
    }
    finally {
        Pop-Location
    }

    if (!(Test-Path -LiteralPath $Output -PathType Leaf)) { Fail 'fused-release precheck report was not generated' }
    $report = Get-Content -LiteralPath $Output -Raw | ConvertFrom-Json
    if ($report.precheck_version -ne $RequiredPrecheckVersion) { Fail 'unexpected precheck version' }
    if ($report.baseline_package_integrity -ne 'PASS') { Fail 'baseline package integrity did not pass' }
    if ($report.baseline_causal_r6_producer_ready -ne $false) { Fail 'baseline producer lock is not false' }
    if ($report.baseline_execution_hard_locked -ne $true) { Fail 'baseline execution is not hard-locked' }
    if ($report.fresh_seal_matches_supplied_seal -ne $true) { Fail 'fresh seal does not match supplied seal' }
    if ($report.candidate_admission_ready -ne $true) { Fail 'candidate admission is not ready' }
    if ($report.canonical_reference_replay_pass -ne $true) { Fail 'canonical-reference replay authority did not pass' }
    if ([string]::IsNullOrWhiteSpace([string]$report.authority_version)) { Fail 'precheck missing authority_version' }
    if ($report.trusted_producer_replay_pass -ne $true) { Fail 'trusted producer replay did not pass' }
    if ($report.producer_source_policy_pass -ne $true) { Fail 'producer source policy did not pass' }
    foreach ($field in @('reference_stream_sha256','reference_replay_attestation_sha256')) {
        $value = [string]$report.$field
        if ($value.Length -ne 64 -or $value -notmatch '^[0-9a-fA-F]{64}$') { Fail ('precheck missing valid ' + $field) }
    }
    if ($report.eligible_for_future_fused_build -ne $true) { Fail 'candidate is not eligible for future fused build' }
    if ($report.fused_package_created -ne $false) { Fail 'precheck may not create a fused package' }
    if ($report.readiness_switch_changed -ne $false) { Fail 'precheck may not change readiness switch' }
    if ($report.execution_unlocked -ne $false) { Fail 'precheck may not unlock execution' }
    if ($report.final_holdout_accessed -ne $false) { Fail 'precheck reports Final Holdout access' }
    if ($report.strategy_retuned -ne $false) { Fail 'precheck reports strategy retuning' }
    if ($report.successor_release_required -ne $true) { Fail 'precheck must require a separate successor release' }

    Write-Host ''
    Write-Host '[PASS] Sealed R6 producer candidate passed canonical-reference authority, trusted replay and parity admission.' -ForegroundColor Green
    Write-Host ('Precheck: ' + $Output)
    Write-Host 'No code was integrated, no readiness switch was changed, and execution remains locked.' -ForegroundColor Yellow
}
finally {
    if (Test-Path -LiteralPath $Work) {
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
}
