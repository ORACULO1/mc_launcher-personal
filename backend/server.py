"""Motor de Chechenitza Studio (Python), controlado por la ventana Tauri.

Protocolo: JSON por líneas.
  entrada (stdin) : {"id": 1, "method": "list_instances", "args": [...]}
  salida  (stdout): {"id": 1, "ok": true, "result": ...}  |  {"id": 1, "ok": false, "error": "..."}
                    {"event": "game_closed", "payload": {...}}     (eventos espontáneos hacia la interfaz)
Todo lo que se imprima con print() va a stderr para no mezclarse con el protocolo.
"""
import json
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

# stdout queda reservado para el protocolo
_proto = sys.stdout
sys.stdout = sys.stderr
try:
    sys.stdin.reconfigure(encoding="utf-8")
    _proto.reconfigure(encoding="utf-8", newline="\n")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths  # noqa: E402
import presence  # noqa: E402
import discord_presence  # noqa: E402
from bridge import Api  # noqa: E402

_write_lock = threading.Lock()


def _send(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False, default=str)
    with _write_lock:
        _proto.write(line + "\n")
        _proto.flush()


def _public(method: str) -> bool:
    return bool(method) and not method.startswith("_")


def _handle(api: Api, msg: dict) -> None:
    mid = msg.get("id")
    method = str(msg.get("method") or "")
    args = msg.get("args") or []
    try:
        fn = getattr(api, method, None) if _public(method) else None
        if not callable(fn):
            raise AttributeError(f"Método desconocido: {method}")
        result = fn(*args)
        _send({"id": mid, "ok": True, "result": result})
    except Exception as e:  # noqa: BLE001
        paths.log_event("server", f"{method}: {e}\n{traceback.format_exc(limit=3)}")
        _send({"id": mid, "ok": False, "error": str(e) or e.__class__.__name__})


def main() -> None:
    api = Api()
    api._emit_hook = lambda event, payload: _send({"event": event, "payload": payload})
    pool = ThreadPoolExecutor(max_workers=24)
    _send({"event": "backend_ready", "payload": {}})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        pool.submit(_handle, api, msg)

    # stdin cerrado: la ventana se cerró
    try:
        presence.clear_heartbeat()
        discord_presence.close()
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
