# Build Cable Designer for Windows: single CableDesigner.exe, plus an installer if Inno Setup is installed.
# Run from the repository root in PowerShell:   .\packaging\build.ps1
$ErrorActionPreference = "Stop"
python -m venv .venv-build
.\.venv-build\Scripts\python -m pip install --upgrade pip
.\.venv-build\Scripts\python -m pip install -r requirements-desktop.txt pyinstaller
.\.venv-build\Scripts\pyinstaller packaging\cable_designer.spec --noconfirm --clean
# The exe is a windowed app, so wait for it explicitly and check its exit code
$p = Start-Process -FilePath .\dist\CableDesigner.exe -ArgumentList "--smoke-test", "dist\smoke-test" -Wait -PassThru -NoNewWindow
if ($p.ExitCode -ne 0) { throw "Smoke test of the packaged app failed (exit $($p.ExitCode))" }
$version = (.\.venv-build\Scripts\python -c "import cable_desktop; print(cable_desktop.__version__)")
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) { $iscc = Get-Item "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue }
if ($iscc) { & $iscc "/DAppVersion=$version" packaging\installer.iss } else { Write-Host "Inno Setup not found: skipping the installer (dist\CableDesigner.exe is ready)." }
