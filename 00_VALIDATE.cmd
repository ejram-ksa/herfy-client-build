@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\release\VALIDATE_SOURCE.ps1" %*
exit /b %ERRORLEVEL%
