@echo off
REM Compila el motor de Python (backend) con Nuitka: traduce el Python a codigo C y genera un
REM binario real, en vez del bytecode de Python que usaba la version anterior (PyInstaller).
REM Resultado: src-tauri\binaries\chechenitza-backend-x86_64-pc-windows-msvc.exe
cd /d "%~dp0\.."
echo Instalando dependencias de Python...
py -m pip install -r requirements.txt --quiet || goto :error
set "OUT=%CD%\src-tauri\binaries\chechenitza-backend-x86_64-pc-windows-msvc.exe"
if exist "%OUT%" del /q "%OUT%"
echo Compilando el motor con Nuitka (la primera vez puede tardar bastante y pedir descargar un compilador de C)...
py -m nuitka ^
  --standalone ^
  --onefile ^
  --assume-yes-for-downloads ^
  --company-name="Chechenitza Studio" ^
  --product-name="Chechenitza Studio Backend" ^
  --file-version=1.1.4.0 ^
  --product-version=1.1.4.0 ^
  --output-dir="%CD%\build\nuitka" ^
  --output-filename=chechenitza-backend-x86_64-pc-windows-msvc.exe ^
  --include-data-files="%CD%\frontend\instances.json=frontend\instances.json" ^
  --include-package=minecraft_launcher_lib ^
  --include-package-data=minecraft_launcher_lib ^
  --include-package=cryptography ^
  --include-package-data=cryptography ^
  --nofollow-import-to=tkinter ^
  --nofollow-import-to=test ^
  --nofollow-import-to=unittest ^
  --python-flag=no_docstrings ^
  --remove-output ^
  "%CD%\backend\server.py" || goto :error
move /y "%CD%\build\nuitka\chechenitza-backend-x86_64-pc-windows-msvc.exe" "%OUT%" >nul || goto :error
echo Motor compilado.
exit /b 0
:error
echo ERROR al compilar el motor de Python.
exit /b 1
