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

$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue

if ($null -eq $nvidiaSmi) {
    throw "nvidia-smi was not found. Install/update the NVIDIA driver first."
}

Write-Host "NVIDIA:"
& nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

Write-Host ""
Write-Host "Creating dedicated Python $PythonVersion environment:"
Write-Host "  $VenvDir"

if (-not (Test-Path $PythonExe)) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $PyLauncher) {
        throw "Windows Python launcher 'py' was not found."
    }
    & py "-$PythonVersion" -m venv $VenvDir
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
