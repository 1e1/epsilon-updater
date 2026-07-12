@echo off
REM Windows - double-click to launch nwupdater (opens the UI in your browser).
REM Works whether nwupdater is installed (pip) or run from a copy of the repo.

where nwupdater >nul 2>&1 && ( nwupdater ui & goto :eof )

REM otherwise run from the source tree: this .bat lives in packaging\launchers\
cd /d "%~dp0..\.."
if exist "src\nwupdater" (
  set PYTHONPATH=src
  py -3 -m nwupdater.cli ui 2>nul || python -m nwupdater.cli ui
  goto :eof
)

echo nwupdater est introuvable.
echo   - installez-le :  pip install nwupdater      (puis relancez ce fichier), ou
echo   - placez ce fichier dans une copie du depot (dossier contenant src\nwupdater).
pause
