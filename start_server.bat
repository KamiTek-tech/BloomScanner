@echo off
title BTC Bloom Scanner GUI Server
chcp 65001 >nul

echo ============================================
echo   🔐 BTC Bloom Scanner — GUI Server
echo   🐍 Python 3.12 (forced)
echo ============================================
echo.

:: 🔧 ПУТЬ К PYTHON 3.12 (используй свой, если отличается)
set PYTHON_CMD=py -3.12

:: 🔧 ПУТЬ К ПАПКЕ ПРОЕКТА
set PROJECT_DIR=%~dp0

:: Переходим в папку проекта
cd /d "%PROJECT_DIR%"

:: 🔍 Проверяем что файлы на месте
if not exist "web_gui.py" (
    echo ❌ ERROR: web_gui.py not found in %PROJECT_DIR%
    echo 💡 Make sure you run this .bat from the correct folder
    pause
    exit /b 1
)

:: 🔍 Проверяем что bit установлен
echo 🔍 Checking dependencies...
%PYTHON_CMD% -c "from bit import PrivateKey; print('✅ bit: OK')" 2>nul
if errorlevel 1 (
    echo.
    echo ❌ ERROR: bit library not found for Python 3.12
    echo.
    echo 💡 Run this command FIRST:
    echo    py -3.12 -m pip install bit mnemonic requests tqdm flask flask-socketio
    echo.
    pause
    exit /b 1
)
echo ✅ All dependencies OK
echo.

:: 🚀 Запускаем сервер
echo 🚀 Starting Flask server...
echo 📍 Open in browser: http://localhost:5000
echo.
echo Press CTRL+C to stop the server
echo ============================================
echo.

%PYTHON_CMD% web_gui.py

:: Если сервер упал — показываем ошибку и ждём
echo.
echo ============================================
echo ⚠️  Server stopped (error or CTRL+C)
echo ============================================
pause