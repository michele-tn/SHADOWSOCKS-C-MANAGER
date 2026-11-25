@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment...
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import PySide6.QtWidgets, pydantic" >nul 2>&1
if errorlevel 1 (
  echo Installing pinned GUI dependencies from PyPI...
  ".venv\Scripts\python.exe" -m pip install -r requirements-gui.txt
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" launch_gui.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Review the error above and README.md.
pause
exit /b 1
