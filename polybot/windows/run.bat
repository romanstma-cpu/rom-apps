@echo off
rem PolyBot launcher for Windows (source install).
rem Requires Python 3.10+ from https://python.org (check "Add to PATH").
cd /d "%~dp0.."
if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
if not exist config.yaml copy config.example.yaml config.yaml
python -m polybot ui
pause
