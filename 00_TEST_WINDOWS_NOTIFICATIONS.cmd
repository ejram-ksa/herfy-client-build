@echo off
setlocal EnableExtensions

set "EXE=%ProgramFiles%\Herfy Client\HerfyClient.exe"
if exist "%EXE%" goto run_test

if defined HERFY_BUILD_ROOT (
  set "EXE=%HERFY_BUILD_ROOT%\dist\HerfyClient\HerfyClient.exe"
  if exist "%EXE%" goto run_test
)

for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "$v=(Get-Content -Raw -Encoding UTF8 '%~dp0version.json'|ConvertFrom-Json).app_version; $v.Replace('.','')"`) do set "VERSION_TOKEN=%%V"
if not defined VERSION_TOKEN (
  echo FAILED: Could not read app_version from version.json.
  exit /b 1
)
if not defined SystemDrive set "SystemDrive=C:"
set "EXE=%SystemDrive%\HerfyBuild\%VERSION_TOKEN%\dist\HerfyClient\HerfyClient.exe"
if exist "%EXE%" goto run_test

echo FAILED: HerfyClient.exe was not found.
echo Install the application or run 00_BUILD_AND_PUBLISH.cmd first.
exit /b 1

:run_test
echo Testing:
echo %EXE%
"%EXE%" --notification-self-check
if errorlevel 1 exit /b %errorlevel%

echo.
echo A real Windows notification and its sound will now be displayed.
"%EXE%" --notification-demo
if errorlevel 1 exit /b %errorlevel%

echo HERFY_WINDOWS_NOTIFICATION_DEMO_OK
exit /b 0
