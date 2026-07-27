@echo off
setlocal
python "%~dp0build\release\verify_deployed_release.py" %*
exit /b %ERRORLEVEL%
