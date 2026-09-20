@echo off
rem ===========================================================================
rem  Same install, run from the Python source instead of the frozen .exe.
rem
rem  Use this when antivirus quarantines install_cn_patch.exe, or when you want
rem  to read the code that is about to modify your game folder.
rem
rem  Needs Python 3.10 or newer (python.org) and the packages in requirements.txt
rem  (this file installs them into your user site-packages for you).
rem ===========================================================================
setlocal
cd /d "%~dp0"
set "GAMEARG="
if not "%~1"=="" set "GAMEARG=--game "%~1""

set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto nopython

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython

echo Installing the Python requirements ...
%PY% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto nopip

%PY% "%~dp0install_cn_patch.py" %GAMEARG%
goto done

:nopython
echo [X] Python was not found.  Install Python 3.10+ from https://www.python.org/
echo     (tick "Add python.exe to PATH" in the installer), then run this file again.
goto done

:oldpython
echo [X] This Python is older than 3.10.  Install a newer one from python.org.
goto done

:nopip
echo [X] "pip install -r requirements.txt" failed.  Run it by hand to see why:
echo         %PY% -m pip install -r requirements.txt
goto done

:done
echo.
pause
endlocal
