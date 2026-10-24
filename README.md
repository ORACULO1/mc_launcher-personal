# Chechenitza Studio (Tauri + NSIS)

Misma estructura que Eufonia Client: ventana **Tauri 2** (Rust), instalador **NSIS** y actualizador
integrado (**tauri-plugin-updater**). El motor del launcher (Python: Minecraft, mods, cuentas, skins…)
va como programa auxiliar (`chechenitza-backend`) que la ventana controla por stdin/stdout.

```
frontend/      interfaz (HTML/JS/CSS) + tauri-bridge.js (conecta con Tauri y actualiza solo)
backend/       motor Python (server.py es el punto de entrada)
src-tauri/     ventana Tauri en Rust + configuración del instalador NSIS y del actualizador
scripts/       build-backend.bat, bump_version.py
keys/          clave de firma de las actualizaciones (la privada NO se sube a GitHub)
```

## Compilar en tu PC (Windows)
Necesitas Python 3.11+, Node.js y Rust (https://rustup.rs). Luego:

    build.bat

El instalador queda en `src-tauri\target\release\bundle\nsis\Chechenitza Studio_<versión>_x64-setup.exe`.

## Publicar una actualización (los launchers se actualizan solos)
1. Una sola vez: en GitHub (repo `ORACULO1/mc_launcher-personal`) → Settings → Secrets and variables → Actions →
   New repository secret → nombre `TAURI_SIGNING_PRIVATE_KEY`, valor = **contenido** de `keys/chechenitza.key`.
2. Cambia la versión: `python scripts/bump_version.py 2.0.1`
3. `git commit -am "v2.0.1"`, `git tag v2.0.1`, `git push --tags`

GitHub Actions compila y publica la release con el instalador y `latest.json`. Al abrir el launcher, cada
usuario descarga e instala la nueva versión sin pulsar nada y el launcher se reinicia.

El repositorio debe ser **público** (el actualizador descarga desde
`https://github.com/ORACULO1/mc_launcher-personal/releases/latest/download/latest.json`).
Si cambias de repositorio, edita `endpoints` en `src-tauri/tauri.conf.json`.

## Importante
* Guarda `keys/chechenitza.key`: sin ella no se pueden firmar actualizaciones (y las ya instaladas no aceptarían otra clave).
* Esta versión es una instalación nueva respecto al launcher antiguo (Inno Setup): desinstala el viejo una vez.
  Tus datos (instancias, ajustes, sesión) no se tocan: siguen en las mismas carpetas.

## Protección del contenido del .exe
`build.bat` hace dos cosas para dificultar que alguien abra el instalador y lea lo de dentro:
* **Motor (Python):** se compila con **Nuitka**, que traduce el código a C y genera un binario real,
  en vez de llevar el bytecode de Python (que se puede extraer y volver a leer casi tal cual).
* **Interfaz (HTML/JS/CSS):** `scripts/build-frontend.mjs` copia `frontend/` a `build/frontend-dist/`,
  ofusca `app.js` y `tauri-bridge.js` (nombres, cadenas de texto cifradas) y minifica `style.css`.
  Es lo que de verdad se empaqueta en el instalador; la carpeta `frontend/` sigue siendo la que editas.

Nada de esto es irrompible: quien le dedique tiempo y conocimiento puede llegar a leerlo igual. Lo que
consigue es que haga falta mucho más esfuerzo, y sobre todo que no quede ningún secreto de verdad (claves,
contraseñas) escrito en el código: esos nunca deben depender de que el .exe no se pueda abrir.
