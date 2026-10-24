@echo off
REM Compila Chechenitza Studio (Tauri + NSIS) y genera el instalador y los archivos de actualizacion.
REM Requisitos en tu PC: Python 3.11+ (comando "py"), Node.js y Rust (https://rustup.rs).
cd /d "%~dp0"

call scripts\build-backend.bat || exit /b 1

echo Instalando dependencias de Node...
call npm install --no-audit --no-fund || exit /b 1

echo Preparando la interfaz para el instalador...
call node scripts\build-frontend.mjs || exit /b 1

REM Clave con la que se firman las actualizaciones (la misma que la clave publica de tauri.conf.json)
if not defined TAURI_SIGNING_PRIVATE_KEY set "TAURI_SIGNING_PRIVATE_KEY=%CD%\keys\chechenitza.key"
if not defined TAURI_SIGNING_PRIVATE_KEY_PASSWORD set "TAURI_SIGNING_PRIVATE_KEY_PASSWORD="

echo Compilando Chechenitza Studio (la primera vez tarda varios minutos)...
echo.| call npx tauri build || exit /b 1

echo.
echo Listo. El instalador esta en:
echo   src-tauri\target\release\bundle\nsis\
pause
