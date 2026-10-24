"""Consulta el estado de un servidor de Minecraft (Java) con el protocolo "Server List Ping".

No usa servicios externos: el launcher se conecta directamente al servidor, igual que la lista
de servidores del juego, y lee si está encendido y cuántos jugadores hay.
"""
from __future__ import annotations

import json
import re
import socket
import struct
from typing import Optional

DEFAULT_PORT = 25565
TIMEOUT = 4.0


def _varint(value: int) -> bytes:
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        out += bytes([byte | 0x80 if value else byte])
        if not value:
            return out


def _read_varint(sock: socket.socket) -> int:
    result = 0
    for i in range(5):
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("conexión cerrada")
        byte = chunk[0]
        result |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return result
    raise ValueError("varint demasiado largo")


def _read_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(4096, size - len(data)))
        if not chunk:
            raise ConnectionError("conexión cerrada")
        data += chunk
    return data


def parse_address(address: str) -> tuple[str, Optional[int]]:
    """Acepta 'host', 'host:puerto' y quita esquemas tipo 'minecraft://'."""
    addr = (address or "").strip()
    addr = re.sub(r"^[a-z]+://", "", addr, flags=re.I).split("/")[0].strip()
    if addr.startswith("["):  # IPv6 [::1]:25565
        m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", addr)
        return (m.group(1), int(m.group(2)) if m and m.group(2) else None) if m else (addr, None)
    if addr.count(":") == 1:
        host, port = addr.split(":")
        if port.isdigit():
            return host, int(port)
    return addr, None


def _srv_lookup(host: str) -> Optional[tuple[str, int]]:
    """Si el dominio usa un registro SRV (_minecraft._tcp) lo respeta. Opcional: necesita dnspython."""
    try:
        import dns.resolver  # type: ignore
        answers = dns.resolver.resolve(f"_minecraft._tcp.{host}", "SRV", lifetime=2.0)
        rec = sorted(answers, key=lambda r: r.priority)[0]
        return str(rec.target).rstrip("."), int(rec.port)
    except Exception:
        return None


def query(address: str) -> dict:
    host, port = parse_address(address)
    if not host:
        return {"ok": False, "error": "Sin dirección de servidor."}
    connect_host, connect_port = host, port or DEFAULT_PORT
    if port is None and not re.match(r"^[\d.]+$", host):
        srv = _srv_lookup(host)
        if srv:
            connect_host, connect_port = srv

    try:
        with socket.create_connection((connect_host, connect_port), timeout=TIMEOUT) as sock:
            sock.settimeout(TIMEOUT)
            host_bytes = host.encode("utf-8")
            handshake = (
                _varint(0x00) + _varint(760)
                + _varint(len(host_bytes)) + host_bytes
                + struct.pack(">H", connect_port) + _varint(1)
            )
            sock.sendall(_varint(len(handshake)) + handshake)
            sock.sendall(_varint(1) + _varint(0x00))   # petición de estado

            _read_varint(sock)                          # longitud del paquete
            if _read_varint(sock) != 0x00:              # id del paquete
                raise ValueError("respuesta inesperada")
            size = _read_varint(sock)
            if size <= 0 or size > 1_000_000:
                raise ValueError("respuesta no válida")
            data = json.loads(_read_exact(sock, size).decode("utf-8", errors="replace"))
    except Exception as e:
        return {"ok": True, "online": False, "error": str(e)}

    players = data.get("players") or {}
    return {
        "ok": True,
        "online": True,
        "players": int(players.get("online", 0) or 0),
        "max": int(players.get("max", 0) or 0),
    }
