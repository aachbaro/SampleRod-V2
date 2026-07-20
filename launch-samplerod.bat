@echo off
REM SampleRod - lanceur dev/local
REM Creer un raccourci vers ce fichier sur le bureau pour lancer SampleRod.

setlocal
cd /d "%~dp0"
set "PYTHON_EXE=%CD%\venv\Scripts\python.exe"

if not exist "app.py" (
    echo Impossible de trouver app.py dans %CD%
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo Venv absent, creation de l'environnement Python...
    py -3 -m venv venv
    if errorlevel 1 (
        echo Echec de creation du venv.
        pause
        exit /b 1
    )

    if exist "requirements.txt" (
        echo Installation des dependances...
        "%PYTHON_EXE%" -m pip install -r requirements.txt
        if errorlevel 1 (
            echo Echec de l'installation des dependances.
            pause
            exit /b 1
        )
    )
)

"%PYTHON_EXE%" -c "import sqlalchemy; import PySide6" >nul 2>nul
if errorlevel 1 (
    if not exist "requirements.txt" (
        echo requirements.txt introuvable, impossible d'installer les dependances manquantes.
        pause
        exit /b 1
    )

    echo Dependances manquantes, installation depuis requirements.txt...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Echec de l'installation des dependances.
        pause
        exit /b 1
    )
)

call "venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Impossible d'activer le venv.
    pause
    exit /b 1
)

echo Demarrage de SampleRod...
"%PYTHON_EXE%" app.py

if errorlevel 1 (
    echo.
    echo SampleRod s'est arrete avec une erreur.
    pause
    exit /b 1
)
