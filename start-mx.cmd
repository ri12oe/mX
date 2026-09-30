@echo off
rem Double-click to start mX. Runs start-mx.ps1 for this session only (doesn't change your execution policy).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-mx.ps1" %*
if errorlevel 1 pause
