@echo off
rem ===========================================================================
rem  Undoes everything the install wrapper did, using <game>\cn_patch_state.json.
rem
rem  Backups (.pre-cn-patch, oujunoshima.exe.orig) are restored, not deleted,
rem  so you can install the patch again afterwards.
rem ===========================================================================
setlocal
cd /d "%~dp0"
set "GAMEARG="
if not "%~1"=="" set "GAMEARG=--game "%~1""

if exist "%~dp0install_cn_patch.exe" (
    "%~dp0install_cn_patch.exe" --uninstall %GAMEARG%
    goto done
)

set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo [X] Neither install_cn_patch.exe nor Python was found.
    goto done
)
%PY% "%~dp0install_cn_patch.py" --uninstall %GAMEARG%

:done
echo.
pause
endlocal
