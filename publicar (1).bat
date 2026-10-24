@echo off
setlocal
set "SRC=%~dp0"
set "REPO=https://github.com/ORACULO1/mc_launcher-personal.git"
set "WORK=%TEMP%\chechenitza_publish"

where git >nul 2>nul
if errorlevel 1 goto :nogit

if not exist "%SRC%src-tauri\tauri.conf.json" goto :wrongdir
if not exist "%SRC%frontend\app.js" goto :wrongdir

git config --global core.longpaths true
git config --global user.email >nul 2>nul
if errorlevel 1 (
  set /p GMAIL=Tu correo de GitHub: 
  set /p GNAME=Tu nombre: 
  git config --global user.email "%GMAIL%"
  git config --global user.name "%GNAME%"
)

set /p VER=Version a publicar, por ejemplo 1.1.4: 
if "%VER%"=="" goto :err

echo.
echo Descargando el repositorio...
if exist "%WORK%" rmdir /s /q "%WORK%"
git clone "%REPO%" "%WORK%"
if errorlevel 1 goto :err

echo Copiando el proyecto sin la clave privada...
robocopy "%SRC%." "%WORK%" /E /XF chechenitza.key publicar.bat /XD node_modules build target .git >nul

cd /d "%WORK%"
git add -A
if errorlevel 1 goto :err
git commit -m "v%VER%"
if errorlevel 1 goto :err
git push
if errorlevel 1 goto :err

echo Reemplazando el tag v%VER%...
git push origin --delete v%VER% >nul 2>nul
git tag -f v%VER%
git push origin v%VER%
if errorlevel 1 goto :tagerr

echo.
echo Listo. GitHub esta compilando la version %VER%.
echo Mira la pestana Actions de tu repositorio. Cuando termine, abre:
echo https://github.com/ORACULO1/mc_launcher-personal/releases/latest/download/latest.json
pause
exit /b 0

:nogit
echo Git no esta instalado o hay que abrir una ventana nueva.
pause
exit /b 1

:wrongdir
echo Este archivo esta en la carpeta equivocada.
echo Tiene que estar dentro de la carpeta del proyecto, junto a package.json.
pause
exit /b 1

:tagerr
echo No se pudo subir el tag v%VER%. Mandame este mensaje.
pause
exit /b 1

:err
echo Algo fallo. Copia el mensaje de arriba y pasamelo.
pause
exit /b 1
