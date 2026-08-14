"""
main.py — punto de entrada del launcher.

Ejecutar con:
    python main.py

Requiere: pip install -r requirements.txt
"""

from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

import auth
import launcher_core as core

CONFIG_PATH = Path.home() / ".mi_mc_launcher_config.json"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Mi Launcher de Minecraft")
        self.geometry("640x520")
        self.minsize(560, 460)

        self.config_data = load_config()
        self.account: auth.Account | None = None
        self.mc_dir = Path(self.config_data.get("mc_dir", str(core.default_minecraft_directory())))

        self._build_layout()
        self._restore_offline_username()
        self._refresh_version_lists()

    # ---------- construcción de la interfaz ----------

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)

        # --- Encabezado de cuenta ---
        account_frame = ctk.CTkFrame(self)
        account_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        account_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(account_frame, text="Cuenta", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4)
        )

        self.account_status_label = ctk.CTkLabel(account_frame, text="No has iniciado sesión")
        self.account_status_label.grid(row=1, column=0, columnspan=3, sticky="w", padx=12)

        self.offline_username_entry = ctk.CTkEntry(account_frame, placeholder_text="Nombre de usuario (offline)")
        self.offline_username_entry.grid(row=2, column=0, padx=(12, 6), pady=10, sticky="ew")

        ctk.CTkButton(account_frame, text="Entrar offline", command=self._login_offline).grid(
            row=2, column=1, padx=6, pady=10
        )
        ctk.CTkButton(account_frame, text="Entrar con Microsoft", command=self._login_microsoft).grid(
            row=2, column=2, padx=(6, 12), pady=10
        )

        # --- Selección de versión ---
        version_frame = ctk.CTkFrame(self)
        version_frame.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        version_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(version_frame, text="Versión", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4)
        )

        self.snapshot_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            version_frame, text="Mostrar snapshots", variable=self.snapshot_var,
            command=self._refresh_version_lists
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=12)

        ctk.CTkLabel(version_frame, text="Minecraft:").grid(row=2, column=0, padx=(12, 6), pady=6, sticky="w")
        self.vanilla_dropdown = ctk.CTkOptionMenu(version_frame, values=["cargando..."])
        self.vanilla_dropdown.grid(row=2, column=1, padx=(0, 12), pady=6, sticky="ew")

        ctk.CTkLabel(version_frame, text="Mod loader:").grid(row=3, column=0, padx=(12, 6), pady=6, sticky="w")
        self.loader_dropdown = ctk.CTkOptionMenu(
            version_frame, values=["Ninguno", "Forge", "Fabric"], command=self._on_loader_changed
        )
        self.loader_dropdown.grid(row=3, column=1, padx=(0, 12), pady=6, sticky="ew")

        # --- RAM ---
        ram_frame = ctk.CTkFrame(self)
        ram_frame.grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        ram_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ram_frame, text="Memoria RAM asignada (MB)").grid(row=0, column=0, padx=12, pady=10, sticky="w")
        self.ram_slider = ctk.CTkSlider(ram_frame, from_=1024, to=8192, number_of_steps=28,
                                         command=self._on_ram_slide)
        self.ram_slider.set(self.config_data.get("ram_mb", 2048))
        self.ram_slider.grid(row=0, column=1, padx=12, pady=10, sticky="ew")
        self.ram_value_label = ctk.CTkLabel(ram_frame, text=f"{int(self.ram_slider.get())} MB")
        self.ram_value_label.grid(row=0, column=2, padx=(0, 12))

        # --- Progreso ---
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=3, column=0, padx=16, pady=(12, 4), sticky="ew")

        self.progress_label = ctk.CTkLabel(self, text="Listo.")
        self.progress_label.grid(row=4, column=0, padx=16, sticky="w")

        # --- Botón jugar ---
        self.play_button = ctk.CTkButton(
            self, text="INSTALAR Y JUGAR", height=44, font=ctk.CTkFont(size=15, weight="bold"),
            command=self._on_play_clicked
        )
        self.play_button.grid(row=5, column=0, padx=16, pady=16, sticky="ew")

    def _restore_offline_username(self):
        saved = self.config_data.get("offline_username", "")
        if saved:
            self.offline_username_entry.insert(0, saved)

    # ---------- helpers de estado ----------

    def _set_progress(self, text: str, value: int, maximum: int):
        def apply():
            self.progress_label.configure(text=text)
            self.progress_bar.set(value / maximum if maximum else 0)
        self.after(0, apply)

    def _on_ram_slide(self, value):
        mb = int(round(value / 256) * 256)
        self.ram_value_label.configure(text=f"{mb} MB")

    def _on_loader_changed(self, _choice):
        pass  # el loader se lee en el momento de instalar/jugar

    def _refresh_version_lists(self):
        def worker():
            try:
                versions = core.list_vanilla_versions(include_snapshots=self.snapshot_var.get())
            except Exception as e:
                self._show_error("No se pudo obtener la lista de versiones", e)
                return

            def apply():
                self.vanilla_dropdown.configure(values=versions)
                if versions:
                    self.vanilla_dropdown.set(versions[0])
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _show_error(self, title: str, exc: Exception):
        traceback.print_exc()
        self.after(0, lambda: messagebox.showerror(title, str(exc)))

    # ---------- login ----------

    def _login_offline(self):
        username = self.offline_username_entry.get()
        try:
            self.account = auth.login_offline(username)
        except Exception as e:
            messagebox.showerror("Error de inicio de sesión", str(e))
            return
        self.account_status_label.configure(
            text=f"Conectado (offline): {self.account.username}"
        )
        self.config_data["offline_username"] = self.account.username
        save_config(self.config_data)

    def _login_microsoft(self):
        self.account_status_label.configure(text="Iniciando sesión con Microsoft…")

        def worker():
            try:
                account = auth.login_microsoft(
                    status_callback=lambda msg: self.after(0, lambda: self.account_status_label.configure(text=msg))
                )
            except Exception as e:
                self._show_error("Error de inicio de sesión con Microsoft", e)
                self.after(0, lambda: self.account_status_label.configure(text="No has iniciado sesión"))
                return
            self.account = account

            def apply():
                self.account_status_label.configure(
                    text=f"Conectado (Microsoft): {account.username}"
                )
            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- instalar + jugar ----------

    def _on_play_clicked(self):
        if self.account is None:
            messagebox.showwarning("Falta iniciar sesión", "Inicia sesión (offline o con Microsoft) antes de jugar.")
            return

        vanilla_version = self.vanilla_dropdown.get()
        loader = self.loader_dropdown.get()
        ram_mb = int(round(self.ram_slider.get() / 256) * 256)
        self.config_data["ram_mb"] = ram_mb
        self.config_data["mc_dir"] = str(self.mc_dir)
        save_config(self.config_data)

        self.play_button.configure(state="disabled", text="Instalando…")

        def worker():
            try:
                progress = lambda text, val, mx: self._set_progress(text or "Instalando…", val, mx)

                if loader == "Forge":
                    version_id = core.install_forge(vanilla_version, self.mc_dir, progress=progress)
                elif loader == "Fabric":
                    version_id = core.install_fabric(vanilla_version, self.mc_dir, progress=progress)
                else:
                    core.install_vanilla(vanilla_version, self.mc_dir, progress=progress)
                    version_id = vanilla_version

                self._set_progress("Lanzando Minecraft…", 1, 1)
                core.launch(version_id, self.mc_dir, self.account, ram_mb=ram_mb)

                self.after(0, lambda: self.progress_label.configure(text="¡Minecraft en marcha!"))
            except Exception as e:
                self._show_error("Error al instalar/lanzar Minecraft", e)
            finally:
                self.after(0, lambda: self.play_button.configure(state="normal", text="INSTALAR Y JUGAR"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
