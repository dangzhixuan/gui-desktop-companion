$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv not found. Create it and install dependencies first."
}

& $python -m pip install -r (Join-Path $PSScriptRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}
& $python -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "gnomon.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc (Join-Path $PSScriptRoot "installer.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }
} else {
    Write-Host "Inno Setup not found. dist\Gnomon.exe was generated."
}
