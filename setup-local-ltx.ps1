param(
    [string]$PythonVersion = "3.11",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu126"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv-ltx"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements-ltx.txt"

Write-Host ""
Write-Host "============================================================"
Write-Host " VIDEO FACTORY - LOCAL LTX SETUP"
Write-Host "============================================================"
Write-Host ""

function Resolve-NvidiaSmi {

    $command = Get-Command `
        nvidia-smi `
        -ErrorAction SilentlyContinue

    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:WINDIR "System32\nvidia-smi.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        (Join-Path ${env:ProgramW6432} "NVIDIA Corporation\NVSMI\nvidia-smi.exe")
    )

    foreach ($candidate in $candidates) {

        if (
            -not [string]::IsNullOrWhiteSpace($candidate) -and
            (Test-Path $candidate)
        ) {
            return $candidate
        }
    }

    return $null
}


$nvidiaSmi = Resolve-NvidiaSmi

Write-Host "NVIDIA:"

if ($null -ne $nvidiaSmi) {

    Write-Host "  nvidia-smi:"
    Write-Host "    $nvidiaSmi"

    & $nvidiaSmi `
        --query-gpu=name,memory.total,driver_version `
        --format=csv,noheader

}
else {

    Write-Warning (
        "nvidia-smi.exe was not found in PATH or the common " +
        "Windows NVIDIA locations. Setup will continue; the " +
        "PyTorch CUDA preflight below is the authoritative test."
    )

    Write-Host ""
    Write-Host "Windows video adapters:"

    try {

        Get-CimInstance Win32_VideoController |
            Select-Object Name, DriverVersion |
            Format-Table -AutoSize

    }
    catch {

        Write-Warning (
            "Unable to query Win32_VideoController: " +
            $_.Exception.Message
        )
    }
}

Write-Host ""
Write-Host "Creating dedicated Python $PythonVersion environment:"
Write-Host "  $VenvDir"

if (-not (Test-Path $PythonExe)) {

    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue

    if ($null -eq $PyLauncher) {
        throw (
            "Windows Python launcher 'py' was not found. " +
            "Install the current Python launcher, then rerun setup."
        )
    }

    Write-Host ""
    Write-Host "Checking Python $PythonVersion..."

    & py "-$PythonVersion" --version 2>$null

    if ($LASTEXITCODE -ne 0) {

        Write-Host (
            "Python $PythonVersion is not installed. " +
            "Installing it with the Windows Python launcher..."
        )

        & py install $PythonVersion

        if ($LASTEXITCODE -ne 0) {
            throw (
                "Automatic Python $PythonVersion installation failed. " +
                "Run 'py install $PythonVersion' manually and rerun setup."
            )
        }

        Write-Host ""
        Write-Host "Python $PythonVersion installed."
    }

    Write-Host ""
    Write-Host "Creating .venv-ltx..."

    & py "-$PythonVersion" -m venv $VenvDir

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Python $PythonVersion is available, but virtual-environment " +
            "creation failed."
        )
    }
}

if (-not (Test-Path $PythonExe)) {
    throw "Failed to create .venv-ltx."
}

Write-Host ""
Write-Host "Upgrading pip..."
& $PythonExe -m pip install --upgrade pip wheel setuptools

Write-Host ""
Write-Host "Installing CUDA-enabled PyTorch..."
Write-Host "  index: $TorchIndexUrl"
& $PythonExe -m pip install torch torchvision --index-url $TorchIndexUrl

Write-Host ""
Write-Host "Installing Local LTX dependencies..."
& $PythonExe -m pip install -r $Requirements

Write-Host ""
Write-Host "Running Local LTX preflight..."
& $PythonExe (Join-Path $ProjectRoot "src\local_ltx_worker.py") --preflight

if ($LASTEXITCODE -ne 0) {
    throw "Local LTX preflight failed."
}

Write-Host ""
Write-Host "============================================================"
Write-Host " LOCAL LTX ENVIRONMENT READY"
Write-Host "============================================================"
Write-Host ""
Write-Host "First benchmark:"
Write-Host "  . .\enter-dev.ps1"
Write-Host "  python src\local_ltx_benchmark.py --scene 1"
Write-Host ""
Write-Host "The first real generation downloads the model weights."
