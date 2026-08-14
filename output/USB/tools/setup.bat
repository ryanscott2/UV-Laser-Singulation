@echo off
setlocal
cd /d "%~dp0"

echo === Creating the venv (one time) ===
python -m venv venv
if errorlevel 1 (
  echo.
  echo ERROR: 'python' was not found, or the venv failed to build.
  echo Open a fresh PowerShell and check that this prints Python 3.8.10:
  echo     python --version
  echo Then run setup.bat again.
  echo.
  pause
  exit /b 1
)

echo === Installing pyserial + pywin32 from the offline wheels ===
call "venv\Scripts\activate.bat"
python -m pip install --no-index --find-links "wheels" pyserial pywin32
if errorlevel 1 (
  echo.
  echo ERROR: package install failed. Check that the wheels folder is next to this file.
  echo.
  pause
  exit /b 1
)

echo === Registering pywin32 (for the WinLase step) ===
python "venv\Scripts\pywin32_postinstall.py" -install

echo.
echo ============================================================
echo  Setup complete.
echo  From now on: double-click activate.bat, then run:
echo      python optiscan.py info
echo ============================================================
echo.
pause
