//! Chechenitza Studio — ventana Tauri.
//!
//! La interfaz (frontend/) llama a `rpc(method, args)`. Esta capa reenvía cada llamada al motor
//! de Python (sidecar `chechenitza-backend`) por stdin/stdout con JSON por líneas, y devuelve la
//! respuesta. Los eventos del motor (progreso de instalación, juego cerrado…) llegan a la interfaz
//! como el evento `launcher-event`. Minimizar/maximizar/cerrar y el selector de archivos se
//! resuelven aquí, en Rust.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewWindow};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::oneshot;

type Reply = Result<Value, String>;
type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Reply>>>>;

struct Backend {
    child: Mutex<Option<CommandChild>>,
    pending: Pending,
    next_id: AtomicU64,
}

fn handle_line(app: &AppHandle, pending: &Pending, line: &Value) {
    if let Some(event) = line.get("event").and_then(Value::as_str) {
        let payload = line.get("payload").cloned().unwrap_or(Value::Null);
        let _ = app.emit("launcher-event", json!({ "event": event, "payload": payload }));
        return;
    }
    let Some(id) = line.get("id").and_then(Value::as_u64) else { return };
    let tx = pending.lock().ok().and_then(|mut p| p.remove(&id));
    if let Some(tx) = tx {
        let ok = line.get("ok").and_then(Value::as_bool).unwrap_or(false);
        let reply = if ok {
            Ok(line.get("result").cloned().unwrap_or(Value::Null))
        } else {
            Err(line
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("Error en el motor del launcher")
                .to_string())
        };
        let _ = tx.send(reply);
    }
}

fn fail_all(pending: &Pending, message: &str) {
    if let Ok(mut p) = pending.lock() {
        for (_, tx) in p.drain() {
            let _ = tx.send(Err(message.to_string()));
        }
    }
}

fn spawn_backend(app: &AppHandle) -> Result<(), String> {
    let (mut rx, child) = app
        .shell()
        .sidecar("chechenitza-backend")
        .map_err(|e| e.to_string())?
        .spawn()
        .map_err(|e| e.to_string())?;

    let state = app.state::<Backend>();
    *state.child.lock().map_err(|e| e.to_string())? = Some(child);
    let pending = state.pending.clone();
    let app = app.clone();

    tauri::async_runtime::spawn(async move {
        let mut partial = String::new();
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let text = String::from_utf8_lossy(&bytes).to_string();
                    for piece in text.split('\n') {
                        let piece = piece.trim_end_matches('\r');
                        if piece.is_empty() {
                            continue;
                        }
                        let candidate = format!("{partial}{piece}");
                        match serde_json::from_str::<Value>(&candidate) {
                            Ok(value) => {
                                partial.clear();
                                handle_line(&app, &pending, &value);
                            }
                            Err(_) => {
                                // línea troceada: se acumula hasta que complete un JSON válido
                                partial = if candidate.len() > 64 * 1024 * 1024 { String::new() } else { candidate };
                            }
                        }
                    }
                }
                CommandEvent::Terminated(_) | CommandEvent::Error(_) => {
                    fail_all(&pending, "El motor del launcher se ha cerrado");
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

#[tauri::command]
async fn rpc(
    app: AppHandle,
    window: WebviewWindow,
    backend: State<'_, Backend>,
    method: String,
    args: Option<Vec<Value>>,
) -> Result<Value, String> {
    // Ventana y selector de archivos: se atienden aquí.
    match method.as_str() {
        "minimize_window" => {
            let _ = window.minimize();
            return Ok(json!({ "ok": true }));
        }
        "toggle_maximize_window" => {
            if window.is_maximized().unwrap_or(false) {
                let _ = window.unmaximize();
            } else {
                let _ = window.maximize();
            }
            return Ok(json!({ "ok": true }));
        }
        "stop_backend" => {
            // Antes de instalar una actualización: si el motor sigue abierto, bloquea su .exe y el
            // instalador no puede reemplazarlo.
            if let Ok(mut guard) = backend.child.lock() {
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            }
            fail_all(&backend.pending, "El motor del launcher se ha cerrado");
            return Ok(json!({ "ok": true }));
        }
        "close_window" => {
            let _ = window.close();
            return Ok(json!({ "ok": true }));
        }
        "pick_skin_file" => {
            let picked = app
                .dialog()
                .file()
                .add_filter("Imagen PNG", &["png"])
                .blocking_pick_file();
            return Ok(match picked {
                Some(file) => match file.into_path() {
                    Ok(path) => json!({ "ok": true, "path": path.to_string_lossy() }),
                    Err(e) => json!({ "ok": false, "error": e.to_string() }),
                },
                None => json!({ "ok": true, "path": Value::Null }),
            });
        }
        _ => {}
    }

    let id = backend.next_id.fetch_add(1, Ordering::SeqCst);
    let (tx, rx) = oneshot::channel::<Reply>();
    backend
        .pending
        .lock()
        .map_err(|e| e.to_string())?
        .insert(id, tx);

    let line = format!(
        "{}\n",
        json!({ "id": id, "method": method, "args": args.unwrap_or_default() })
    );
    {
        let mut guard = backend.child.lock().map_err(|e| e.to_string())?;
        match guard.as_mut() {
            Some(child) => child.write(line.as_bytes()).map_err(|e| e.to_string())?,
            None => {
                backend.pending.lock().map_err(|e| e.to_string())?.remove(&id);
                return Err("El motor del launcher no está en marcha".into());
            }
        }
    }

    match rx.await {
        Ok(reply) => reply,
        Err(_) => Err("El motor del launcher se ha cerrado".into()),
    }
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Backend {
            child: Mutex::new(None),
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: AtomicU64::new(1),
        })
        .invoke_handler(tauri::generate_handler![rpc])
        .setup(|app| {
            if let Err(e) = spawn_backend(app.handle()) {
                eprintln!("No se pudo iniciar el motor del launcher: {e}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir Chechenitza Studio");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            let backend = handle.state::<Backend>();
            if let Ok(mut guard) = backend.child.lock() {
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            };
        }
    });
}
