@echo off
rem Roptimizer for Windows (checked on Windows 11). Double-click to start.
rem First start: installs uv (astral.sh) if missing, Python 3.13 and the packages into .venv, and the GPU
rem package when an NVIDIA GPU is found. Later starts skip all that. Close this window to stop it.
setlocal
cd /d "%~dp0"
if "%MSO_PORT%"=="" set MSO_PORT=8797
set URL=http://localhost:%MSO_PORT%

curl -fs "%URL%/api/charts" >nul 2>&1 && (echo Roptimizer is already running at %URL% & (if not defined MSO_NO_BROWSER start "" "%URL%") & exit /b 0)

set UV=uv
where uv >nul 2>&1 || (
  if exist "%USERPROFILE%\.local\bin\uv.exe" (set "UV=%USERPROFILE%\.local\bin\uv.exe") else (
    echo Installing uv, the Python installer, from astral.sh ...
    powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv with Python 3.13 ...
  "%UV%" venv -q -p 3.13 .venv || goto :fail
)
if not exist ".venv\.installed" (
  echo Installing the packages, a few minutes the first time ...
  "%UV%" pip install -q -p .venv\Scripts\python.exe -r requirements.txt || goto :fail
  nvidia-smi >nul 2>&1 && (
    echo NVIDIA GPU found: installing cupy-cuda12x[ctk] ...
    "%UV%" pip install -q -p .venv\Scripts\python.exe "cupy-cuda12x[ctk]" || echo The GPU package did not install: runs will use the CPU.
  ) || echo No NVIDIA GPU found: runs will use the CPU, slower and with a smaller scenario bank.
  type nul > .venv\.installed
)

echo Starting Roptimizer at %URL% (close this window to stop it) ...
if not defined MSO_NO_BROWSER start "" /b powershell -NoProfile -Command "for ($i=0; $i -lt 120; $i++) { try { Invoke-WebRequest -UseBasicParsing '%URL%/api/charts' | Out-Null; Start-Process '%URL%'; break } catch { Start-Sleep 1 } }"
.venv\Scripts\python.exe -m app.server
goto :eof

:fail
echo Setup did not finish. The messages above say why.
pause
