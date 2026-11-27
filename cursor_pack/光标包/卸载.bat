@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem ============================================================
rem  Pixel Cat Cursor - Uninstaller (restores default cursors)
rem ============================================================

set "DST=%LOCALAPPDATA%\Cursors\PixelCat"
set "KEY=HKCU\Control Panel\Cursors"

echo ============================================
echo   Pixel Cat Cursor - Uninstaller
echo ============================================
echo.

echo [1/2] Removing registry entries...
reg delete "%KEY%" /v Arrow        /f >nul 2>&1
reg delete "%KEY%" /v Help         /f >nul 2>&1
reg delete "%KEY%" /v AppStarting  /f >nul 2>&1
reg delete "%KEY%" /v Wait         /f >nul 2>&1
reg delete "%KEY%" /v Hand         /f >nul 2>&1
reg delete "%KEY%" /v NWPen        /f >nul 2>&1
reg delete "%KEY%" /v SizeWE       /f >nul 2>&1
reg delete "%KEY%" /v SizeNS       /f >nul 2>&1
reg delete "%KEY%" /v SizeNWSE     /f >nul 2>&1
reg delete "%KEY%" /v SizeNESW     /f >nul 2>&1
reg delete "%KEY%" /v SizeAll      /f >nul 2>&1
reg delete "%KEY%" /v No           /f >nul 2>&1
reg delete "%KEY%" /v IBeam        /f >nul 2>&1

echo [2/2] Removing copied files...
if exist "%DST%" rmdir /s /q "%DST%"

powershell -NoProfile -Command "$s='[System.Runtime.InteropServices.DllImport(\"user32.dll\")] public static extern bool SystemParametersInfo(uint a, uint b, IntPtr c, uint d);'; $t=Add-Type -MemberDefinition $s -Name CursorApi -Namespace Win32 -PassThru; [Win32.CursorApi]::SystemParametersInfo(0x57,0,[IntPtr]::Zero,0) | Out-Null"

echo.
echo Done. Default cursors have been restored.
echo.
pause
