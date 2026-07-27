@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\installer\INSTALL_BUILD_TOOLS.ps1" %*
exit /b %ERRORLEVEL%
