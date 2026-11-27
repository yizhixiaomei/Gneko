@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem ============================================================
rem  Pixel Cat Cursor - One-click installer (current user, no admin)
rem  Copies cursor files to a fixed folder, writes registry, refreshes.
rem ============================================================

set "SRC=%~dp0"
set "DST=%LOCALAPPDATA%\Cursors\PixelCat"
set "KEY=HKCU\Control Panel\Cursors"

echo ============================================
echo   Pixel Cat Cursor - Installer
echo ============================================
echo.

if not exist "%DST%" mkdir "%DST%"

echo [1/3] Copying cursor files...
copy /y "%SRC%Arrow.cur"       "%DST%\" >nul
copy /y "%SRC%Help.cur"        "%DST%\" >nul
copy /y "%SRC%AppStarting.ani" "%DST%\" >nul
copy /y "%SRC%Wait.ani"         "%DST%\" >nul
copy /y "%SRC%Hand.cur"        "%DST%\" >nul
copy /y "%SRC%NWPen.ani"        "%DST%\" >nul
copy /y "%SRC%SizeWE.ani"       "%DST%\" >nul
copy /y "%SRC%SizeNS.ani"       "%DST%\" >nul
copy /y "%SRC%SizeNWSE.ani"     "%DST%\" >nul
copy /y "%SRC%SizeNESW.ani"     "%DST%\" >nul
copy /y "%SRC%SizeAll.ani"      "%DST%\" >nul
copy /y "%SRC%No.cur"          "%DST%\" >nul
copy /y "%SRC%IBeam.cur"       "%DST%\" >nul

echo [2/3] Registering cursor scheme...
reg add "%KEY%" /v Arrow        /t REG_SZ /d "%DST%\Arrow.cur"       /f >nul
reg add "%KEY%" /v Help         /t REG_SZ /d "%DST%\Help.cur"        /f >nul
reg add "%KEY%" /v AppStarting  /t REG_SZ /d "%DST%\AppStarting.ani"  /f >nul
reg add "%KEY%" /v Wait         /t REG_SZ /d "%DST%\Wait.ani"         /f >nul
reg add "%KEY%" /v Hand         /t REG_SZ /d "%DST%\Hand.cur"        /f >nul
reg add "%KEY%" /v NWPen        /t REG_SZ /d "%DST%\NWPen.ani"        /f >nul
reg add "%KEY%" /v SizeWE       /t REG_SZ /d "%DST%\SizeWE.ani"       /f >nul
reg add "%KEY%" /v SizeNS       /t REG_SZ /d "%DST%\SizeNS.ani"      /f >nul
reg add "%KEY%" /v SizeNWSE     /t REG_SZ /d "%DST%\SizeNWSE.ani"     /f >nul
reg add "%KEY%" /v SizeNESW     /t REG_SZ /d "%DST%\SizeNESW.ani"     /f >nul
reg add "%KEY%" /v SizeAll      /t REG_SZ /d "%DST%\SizeAll.ani"      /f >nul
reg add "%KEY%" /v No           /t REG_SZ /d "%DST%\No.cur"          /f >nul
reg add "%KEY%" /v IBeam        /t REG_SZ /d "%DST%\IBeam.cur"       /f >nul

echo [3/3] Refreshing cursors...
powershell -NoProfile -Command "$s='[System.Runtime.InteropServices.DllImport(\"user32.dll\")] public static extern bool SystemParametersInfo(uint a, uint b, IntPtr c, uint d);'; $t=Add-Type -MemberDefinition $s -Name CursorApi -Namespace Win32 -PassThru; [Win32.CursorApi]::SystemParametersInfo(0x57,0,[IntPtr]::Zero,0) | Out-Null"

echo.
echo Done. The pixel-cat cursor scheme has been applied.
echo To uninstall, run "Uninstall.bat" in this folder.
echo.
pause
