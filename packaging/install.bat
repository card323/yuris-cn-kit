@echo off
rem ===========================================================================
rem  Installs the simplified-Chinese patch (A2: rebuild from your own game data)
rem
rem  If the game folder is not found automatically, drag the game folder onto
rem  this file, or run it in a console:  install_cn_patch.exe --game "D:\...\oujunoshima"
rem
rem  This file is plain ASCII on purpose: a console that is not UTF-8 must not
rem  mangle it.  The Chinese text lives in the readme and in the installer
rem  output.
rem ===========================================================================
setlocal
cd /d "%~dp0"
set "GAMEARG="
if not "%~1"=="" set "GAMEARG=--game "%~1""

if not exist "%~dp0install_cn_patch.exe" goto noexe
"%~dp0install_cn_patch.exe" %GAMEARG%
goto done

:noexe
echo [X] install_cn_patch.exe is not next to this file.
echo     Unzip the whole archive first, do not run the .bat from inside the zip.
pause
exit /b 1

:done
echo.
pause
endlocal
