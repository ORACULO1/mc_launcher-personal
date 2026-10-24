"""Barra de progreso que solo avanza.

Minecraft descarga en varias fases (librerías, recursos, Java…) y cada archivo reinicia el contador,
así que la barra "iba hacia delante y hacia atrás". Aquí cada fase nueva consume una parte de lo que
queda de barra: avanza siempre, nunca retrocede y no llega al 100 % hasta que de verdad termina.
"""
from __future__ import annotations

PHASE_SHARE = 0.6       # cada fase llena el 60 % de la barra que aún queda
MILESTONE_FLOOR = 0.9   # hitos del propio launcher ("Comprobando archivos…"): barra casi llena
SCALE = 1000


class SmoothProgress:
    def __init__(self) -> None:
        self.overall = 0.0
        self._start = 0.0
        self._max: int | None = None
        self._value = 0

    def update(self, value: int, maximum: int) -> tuple[int, int]:
        """Recibe el progreso bruto de una fase y devuelve (valor, máximo) listo para pintar."""
        if maximum <= 1:
            # Solo cambia el texto (o es un hito): nunca mueve la barra hacia atrás.
            if value >= 1:
                self.overall = max(self.overall, MILESTONE_FLOOR)
            return int(self.overall * SCALE), SCALE
        if maximum != self._max or value < self._value:      # empieza una fase nueva
            self._start = self.overall
            self._max = maximum
        self._value = value
        frac = min(1.0, max(0.0, value / maximum))
        target = self._start + (1.0 - self._start) * PHASE_SHARE * frac
        self.overall = max(self.overall, min(target, 0.995))
        return int(self.overall * SCALE), SCALE

    def finish(self) -> tuple[int, int]:
        """Fuerza el 100% real. Se usa en el paso final de verdad (justo antes de lanzar el
        juego), para que la barra siempre termine llena en vez de quedarse cerca del final."""
        self.overall = 1.0
        return SCALE, SCALE
