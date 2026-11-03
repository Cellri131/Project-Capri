@echo off
REM Lance Capri en arriere-plan (sans fenetre console)
cd /d "%~dp0"
start "" pythonw "%~dp0assistant_vocal.py"
