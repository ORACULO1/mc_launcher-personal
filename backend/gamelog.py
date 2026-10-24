"""Resume los errores del juego tras cada partida, para poder diagnosticar un mod que no funciona
(por ejemplo, el vídeo de FancyMenu). Solo se anotan las líneas relevantes de logs/latest.log en access.log;
se oculta el nombre de usuario de Windows de las rutas."""
from __future__ import annotations

import re
from pathlib import Path

_ERROR = re.compile(r"\b(ERROR|FATAL)\b|Exception|AccessDenied|NoSuchFile|FileNotFound|IOException|denied", re.I)
_MODS = re.compile(r"fancymenu|watermedia|vlc|melody|konkrete|ffmpeg|video", re.I)
# El nombre de usuario de Windows puede tener espacios y tildes ("Juan Pérez"): se quita entero, hasta la siguiente barra.
_USER = re.compile(r"(?i)([A-Z]:[\\/]Users[\\/])[^\\/\r\n\"'<>|:*?]+?(?=[\\/\"'<>|:]|$)")


def summarize(log_path: Path, max_errors: int = 30, max_mod_lines: int = 15,
              max_len: int = 300, tail_bytes: int = 2_000_000) -> list[str]:
    """Devuelve las líneas del log que parecen errores o que mencionan mods de vídeo/menús."""
    try:
        path = Path(log_path)
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    picked: list[tuple[int, str]] = []
    errors = mods = 0
    seen: set[str] = set()
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line or line in seen:
            continue
        is_error = bool(_ERROR.search(line))
        is_mod = bool(_MODS.search(line))
        if is_error and errors < max_errors:
            errors += 1
        elif is_mod and mods < max_mod_lines:
            mods += 1
        else:
            continue
        seen.add(line)
        picked.append((i, _USER.sub(r"\1<usuario>", line)[:max_len]))
    return [line for _, line in picked]
