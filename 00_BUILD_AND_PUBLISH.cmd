@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\release\BUILD_AND_PUBLISH.ps1" %*
exit /b %ERRORLEVEL%
