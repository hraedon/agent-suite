# Agent Suite Windows Installer
#
# Usage: .\install-windows.ps1 [-Profile A|B|C] [-DryRun]
#
# This script:
# 1. Checks prerequisites (Python 3.12+, pip, PowerShell)
# 2. Creates C:\ProgramData\agent-suite\ directory structure
# 3. Installs agent-suite via pip
# 4. Runs preflight
# 5. Configures services (if profile requires)
# 6. Runs doctor

param(
    [ValidateSet("A", "B", "C")]
    [string]$SuiteProfile = "B",

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$BaseDir = "C:\ProgramData\agent-suite"
$SubDirs = @("bin", "services", "logs")

function Write-Step {
    param([string]$Message)
    Write-Host "[agent-suite] $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  OK: $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  FAIL: $Message" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# Step 1: Check prerequisites
# ---------------------------------------------------------------------------

Write-Step "Checking prerequisites..."

# Python 3.12+
$pyVersionStr = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Python not found. Install Python 3.12+ and add it to PATH."
    exit 1
}
$pyParts = $pyVersionStr -split '\.'
$pyMajor = [int]$pyParts[0]
$pyMinor = [int]$pyParts[1]
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 12)) {
    Write-Fail "Python $pyVersionStr is too old. Requires >= 3.12."
    exit 1
}
Write-Ok "Python $pyVersionStr"

# pip
& python -m pip --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip not available. Install pip."
    exit 1
}
Write-Ok "pip available"

# PowerShell version (informational)
Write-Ok "PowerShell $($PSVersionTable.PSVersion)"

# ---------------------------------------------------------------------------
# Step 2: Create directory structure
# ---------------------------------------------------------------------------

Write-Step "Creating directory structure at $BaseDir..."

foreach ($sub in $SubDirs) {
    $path = Join-Path $BaseDir $sub
    if (-not (Test-Path $path)) {
        if ($DryRun) {
            Write-Host "  [dry-run] would create $path" -ForegroundColor Yellow
        } else {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
            Write-Ok "created $path"
        }
    } else {
        Write-Ok "$path already exists"
    }
}

# ---------------------------------------------------------------------------
# Step 3: Install agent-suite
# ---------------------------------------------------------------------------

Write-Step "Installing agent-suite[windows-full]..."

if ($DryRun) {
    Write-Host "  [dry-run] would run: pip install agent-suite[windows-full]" -ForegroundColor Yellow
} else {
    & python -m pip install "agent-suite[windows-full]"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "pip install failed."
        exit 1
    }
    Write-Ok "agent-suite installed"
}

# ---------------------------------------------------------------------------
# Step 4: Run preflight
# ---------------------------------------------------------------------------

Write-Step "Running preflight (profile $SuiteProfile)..."

$preflightOutput = & agent-suite preflight --profile $SuiteProfile --json 2>$null
$preflightExit = $LASTEXITCODE

if ($preflightExit -ne 0) {
    Write-Fail "preflight returned exit code $preflightExit"
    Write-Host $preflightOutput
    exit 1
}

$preflight = $preflightOutput | ConvertFrom-Json
Write-Ok "preflight state: $($preflight.state)"

if ($preflight.state -ne "ready") {
    Write-Fail "preflight is not ready — resolve blockers before proceeding."
    Write-Host ($preflight | ConvertTo-Json -Depth 10)
    exit 1
}

# ---------------------------------------------------------------------------
# Step 5: Configure services (if not dry-run)
# ---------------------------------------------------------------------------

if (-not $DryRun) {
    Write-Step "Installing services (agent-suite setup-install --apply)..."
    & agent-suite setup-install --apply --profile $SuiteProfile
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "setup install failed."
        exit 1
    }
    Write-Ok "services installed"
} else {
    Write-Step "[dry-run] would run: agent-suite setup-install --apply --profile $SuiteProfile"
}

# ---------------------------------------------------------------------------
# Step 6: Run doctor
# ---------------------------------------------------------------------------

Write-Step "Running doctor..."

$doctorOutput = & agent-suite doctor --json 2>$null
$doctorExit = $LASTEXITCODE

if ($doctorExit -ne 0) {
    Write-Fail "doctor returned exit code $doctorExit"
    Write-Host $doctorOutput
    exit 1
}

$doctor = $doctorOutput | ConvertFrom-Json
if ($doctor.suite_ok) {
    Write-Ok "doctor: suite is healthy"
} else {
    Write-Fail "doctor: suite is not healthy"
    Write-Host ($doctor | ConvertTo-Json -Depth 10)
    exit 1
}

Write-Step "Installation complete."
exit 0
