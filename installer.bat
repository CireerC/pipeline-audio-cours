@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Installation - pipeline cours
echo.
echo ===== Installation de la pipeline cours =====
echo.

rem --- Python 3.11+ ---
where python >nul 2>nul
if errorlevel 1 goto :nopython
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto :oldpython
echo [OK] Python
python -c "import tkinter" 2>nul
if errorlevel 1 echo [!] tkinter manquant : reinstalle Python depuis python.org en cochant "tcl/tk and IDLE".

rem --- Paquets Python ---
echo.
echo --- Installation des paquets Python : requests, playwright ---
python -m pip install -r requirements.txt
if errorlevel 1 goto :piperror
echo [OK] Paquets Python

rem --- ffmpeg ---
where ffmpeg >nul 2>nul
if errorlevel 1 goto :noffmpeg
echo [OK] ffmpeg

rem --- Claude Code ---
where claude >nul 2>nul
if errorlevel 1 goto :noclaude
echo [OK] Claude Code

rem --- Microsoft Edge ---
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" goto :edgeok
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" goto :edgeok
echo [!] Microsoft Edge introuvable : il est necessaire pour la transcription Mistral.
goto :config
:edgeok
echo [OK] Microsoft Edge

rem --- Config perso ---
:config
if exist config.toml goto :configok
copy /y config.example.toml config.toml >nul
echo [OK] config.toml cree : ouvre-le pour mettre tes matieres.
goto :login
:configok
echo [OK] config.toml deja present

rem --- Connexion Mistral ---
:login
echo.
echo --- Connexion a Mistral ---
echo Une fenetre Edge va s'ouvrir : connecte-toi a ton compte Mistral, gratuit.
echo Elle se ferme toute seule une fois sur la page Reconnaissance vocale.
pause
python cours.py login

rem --- Verification finale ---
echo.
echo --- Verification finale ---
python cours.py verifier
echo.
echo Installation terminee. Pour enregistrer un cours : double-clic sur enregistrer_cours.bat
pause
exit /b 0

:nopython
echo [X] Python introuvable. Installe Python 3.11 ou plus : https://www.python.org/downloads/
echo     Coche "Add python.exe to PATH" pendant l'installation, puis relance ce script.
pause
exit /b 1

:oldpython
echo [X] Python 3.11 ou plus est necessaire. Installe la derniere version : https://www.python.org/downloads/
pause
exit /b 1

:piperror
echo [X] L'installation des paquets Python a echoue : regarde le message ci-dessus.
pause
exit /b 1

:noffmpeg
echo [!] ffmpeg introuvable : installation avec winget...
winget install --id Gyan.FFmpeg -e
echo.
echo     Ferme cette fenetre puis relance installer.bat pour que ffmpeg soit pris en compte.
pause
exit /b 1

:noclaude
echo [X] Claude Code introuvable. Il faut un abonnement Claude Pro ou Max.
echo     Dans PowerShell, lance :   irm https://claude.ai/install.ps1 ^| iex
echo     Puis tape  claude  et connecte-toi a ton compte. Relance ensuite installer.bat.
pause
exit /b 1
