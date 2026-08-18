import customtkinter as ctk
import csv
import subprocess
import re
import os
from tkinter import messagebox
import shutil
import datetime
import tempfile
import sys

# ============================================================
# LOGGING DE ERRORES (FUNCIONAL)
# ============================================================
LOG_FILE = os.path.join(
    os.path.expanduser("~"),
    "netmap_error_log.txt"
)

# Alias para compatibilidad con código existente
def log_error(message, context=None):
    log_event("ERROR", message, context)

def log_event(level, message, context=None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 100 + "\n")
            f.write(f"[{timestamp}] {level.upper()}\n")
            f.write(f"MENSAJE: {message}\n")
            if context:
                f.write("\nCONTEXTO TECNICO:\n")
                for key, value in context.items():
                    f.write(f"\n--- {key.upper()} ---\n")
                    f.write(f"{value}\n")
            if level.upper() in ("WARN", "ERROR"):
                try:
                    os.startfile(LOG_FILE)
                except Exception:
                    pass
    except Exception:
        pass

# ============================================================
# Credenciales
# ============================================================
UNC_USER = "administrator"
UNC_PASS = "admin#1234"

# UI defaults
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ============================================================
# FUNCIONES AUXILIARES DE RUTA UNC DINÁMICA
# ============================================================
def get_unc_path(flag):
    try:
        if flag.upper() == "SUR":
            return r"\\PMX-NFF-01\Reimage\ControlApp.SUR\LineCapture\ARM\netMAP_ARM.csv"
        elif flag.upper() == "NFF":
            return r"\\PMX-NFF-01\Reimage\ControlApp\LineCapture\ARM\netMAP_ARM.csv"
        else:
            raise ValueError("Flag inválido: debe ser SUR o NFF")
    except Exception as e:
        log_error("Error al obtener la ruta UNC", e)
        raise

# ============================================================
# FUNCIONES MAC ADDRESS
# ============================================================
def get_mac_address():
    log_event("INFO", "Inicio de detección de MAC física")
    try:
        output = subprocess.check_output(
            "ipconfig /all",
            encoding="cp437",
            errors="ignore"
        )
        log_event("INFO", "Ejecución de ipconfig /all exitosa")
        adapters = output.split("\n\n")
        valid_adapters = []
        log_event(
            "INFO",
            "Cantidad de bloques de adaptadores detectados",
            {"Total bloques": len(adapters)}
        )
        for idx, block in enumerate(adapters, start=1):
            reasons = []
            block_lower = block.lower()
            if "physical address" not in block_lower:
                reasons.append("No contiene Physical Address")
            if "media disconnected" in block_lower:
                reasons.append("Media disconnected")
            if "ipv4 address" not in block_lower:
                reasons.append("No tiene IPv4 activo")
            excluded_keywords = [
                "bluetooth", "wi-fi direct", "virtual", "vmware", 
                "hyper-v", "vpn", "loopback", "local area connection*"
            ]
            for k in excluded_keywords:
                if k in block_lower:
                    reasons.append(f"Excluido por keyword: {k}")
            mac_match = re.search(
                r"Physical Address[^\n]*:\s*([0-9A-Fa-f\-]{17})",
                block
            )
            mac = mac_match.group(1).replace("-", ":").upper() if mac_match else "NO_DETECTADA"
            context = {
                "Indice adaptador": idx,
                "MAC detectada": mac,
                "Motivos": "\n".join(reasons) if reasons else "Cumple todos los criterios",
                "Bloque completo": block
            }
            if reasons or not mac_match:
                log_event("WARN", f"Adaptador #{idx} descartado", context)
                continue
            log_event("INFO", f"Adaptador #{idx} válido detectado", context)
            valid_adapters.append(mac)
        if not valid_adapters:
            log_event(
                "ERROR",
                "No se encontró ningún adaptador físico válido",
                {
                    "Total adaptadores analizados": len(adapters),
                    "Resultado": "MAC física NO disponible",
                    "Salida ipconfig (parcial)": output[:2500]
                }
            )
            return None
        selected_mac = valid_adapters[0]
        log_event("INFO", "MAC física seleccionada exitosamente", {"MAC final": selected_mac})
        return selected_mac
    except Exception as e:
        log_event(
            "ERROR",
            "Excepción crítica durante detección de MAC",
            {"Tipo excepción": type(e).__name__, "Detalle": str(e)}
        )
        return None

# ============================================================
# FUNCIONES DE ACCESO A CSV CON AUTENTICACIÓN
# ============================================================
def mount_unc(path):
    try:
        cmd = f'net use "{os.path.dirname(path)}" /user:{UNC_USER} {UNC_PASS} /persistent:no'
        subprocess.check_output(cmd, shell=True)
    except Exception as e:
        log_error("No se pudo montar la ruta UNC", e)
        raise

def unmount_unc(path):
    try:
        cmd = f'net use "{os.path.dirname(path)}" /delete'
        subprocess.check_output(cmd, shell=True)
    except Exception:
        pass

def check_file_access(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"No se puede acceder al archivo: {path}")

def copy_to_temp(path):
    mount_unc(path)
    try:
        check_file_access(path)
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, os.path.basename(path))
        shutil.copy2(path, temp_path)
        return temp_path
    except Exception as e:
        log_error("Error al copiar el CSV a temporal", e)
        raise
    finally:
        unmount_unc(path)

def backup_server_file(path, tipo=""):
    mount_unc(path)
    try:
        if not os.path.exists(path):
            return
        folder = os.path.dirname(path)
        backup_path = os.path.join(folder, "netMap_ARM_backup.csv")
        shutil.copy2(path, backup_path)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(backup_path, "r+", encoding="utf-8") as f:
            lines = f.readlines()
            comment = f"# Backup creado el {now} - Modificación: {tipo}\n"
            if not lines or not lines[0].startswith("# Backup creado el"):
                lines.insert(0, comment)
            else:
                lines[0] = comment
            f.seek(0)
            f.writelines(lines)
    except Exception as e:
        log_error("Error al crear backup del CSV", e)
        raise
    finally:
        unmount_unc(path)

def save_csv_server(path, data, tipo=""):
    try:
        temp_path = copy_to_temp(path)
        backup_server_file(path, tipo)
        with open(temp_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(data)
        mount_unc(path)
        try:
            shutil.copy2(temp_path, path)
        finally:
            unmount_unc(path)
    except Exception as e:
        log_error("Error al guardar el CSV en el servidor", e)
        raise

def load_csv_server(path):
    try:
        temp_path = copy_to_temp(path)
        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            with open(temp_path, "r", encoding="utf-8-sig") as f:
                return list(csv.reader(f))
    except Exception as e:
        log_error("Error al cargar el CSV desde el servidor", e)
        raise

def restore_backup_server(path):
    mount_unc(path)
    try:
        folder = os.path.dirname(path)
        backup_path = os.path.join(folder, "netMap_ARM_backup.csv")
        if not os.path.exists(backup_path):
            raise FileNotFoundError("No existe backup disponible en el servidor.")
        with open(backup_path, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        cleaned = []
        for row in rows:
            if not row:
                continue
            first = row[0].strip()
            if first.startswith("#"):
                continue
            if first == "" and len(row) > 1:
                continue
            cleaned.append(row)
        save_csv_server(path, cleaned, tipo="restaurar backup")
    except Exception as e:
        log_error("Error al restaurar el backup del servidor", e)
        raise
    finally:
        unmount_unc(path)

# ============================================================
# ASIGNAR ST DISPONIBLE
# ============================================================
def assign_ST(data, mac, prefix, station, mode):
    if mode == "OFFLINE":
        return prefix + station + "ST99"
    used = []
    for row in data:
        if len(row) > 1 and row[1].startswith(prefix + station):
            m = re.search(r"ST(\d+)", row[1])
            if m:
                used.append(int(m.group(1)))
    for n in range(1, 99):
        if n not in used:
            return f"{prefix}{station}ST{n:02d}"
    return None

# ============================================================
# LIMPIAR CSV AGRUPANDO POR ESTACIONES
# ============================================================
def limpiar_csv_data(data):
    estaciones = {}
    for row in data:
        if not row or not row[0].strip():
            continue
        full = row[1].strip() if len(row) > 1 else ""
        m = re.match(r"(SUT_|SUL_)?([A-Za-z0-9]+)-ST(\d+)", full)
        if not m:
            continue
        estacion = m.group(2)
        st_num = int(m.group(3))
        estaciones.setdefault(estacion, [])
        estaciones[estacion].append((st_num, row))
    output = [["mac", "name", "Des"] + [""] * 17]
    for estacion in sorted(estaciones.keys()):
        output.append([estacion] + [""] * 19)
        for _, row in sorted(estaciones[estacion], key=lambda x: x[0]):
            output.append(row + [""] * (20 - len(row)))
        output.append([""] * 20)
    return output
# ============================================================
# INTERFAZ GRÁFICA
# ============================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ICONO DE LA VENTANA
        icon_path = self.resource_path("jujuicon.ico")
        try:
            self.iconbitmap(icon_path)
        except Exception as e:
            log_event("WARN", f"No se pudo cargar el icono: {e}")

        # CONFIGURACIÓN PRINCIPAL DE LA VENTANA
        self.title("NETMAP Manager")
        self.geometry("600x750")
        self.resizable(False, False)

        # VARIABLES
        self.var_flag = ctk.StringVar(value="SUR")
        self.var_device = ctk.StringVar(value="Laptop")
        self.var_station = ctk.StringVar()
        self.var_mode = ctk.StringVar(value="ONLINE")

        # HEADER
        ctk.CTkLabel(self, text="NETMAP MANAGER", font=("Segoe UI", 30, "bold")).pack(pady=(20, 5))
        ctk.CTkLabel(self, text="Powered by AntonDev", font=("Segoe UI", 12)).pack(pady=(0, 20))

        # TAB VIEW
        self.tab_view = ctk.CTkTabview(self, width=500, height=500)
        self.tab_view.pack(pady=10, padx=40, fill="x")
        self.tab_config = self.tab_view.add("🛠️ Administrar Mapping Table")
        self.tab_maint = self.tab_view.add("🧹 Mantenimiento de Datos")
        self.tab_config.grid_columnconfigure(0, weight=1)

        # FLAG
        flag_frame = ctk.CTkFrame(self.tab_config, fg_color="transparent")
        flag_frame.grid(row=0, column=0, pady=20, padx=20, sticky="ew")
        ctk.CTkLabel(flag_frame, text="FLAG:", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.flag_segmented = ctk.CTkSegmentedButton(flag_frame, values=["SUR", "NFF"], variable=self.var_flag)
        self.flag_segmented.grid(row=0, column=1, sticky="e")
        flag_frame.columnconfigure(1, weight=1)

        # DISPOSITIVO
        self.create_option_group(self.tab_config, "Tipo de dispositivo:", 1, ["Laptop", "Tablet"], self.var_device)

        # ESTACIÓN
        estaciones_display = ["First Reimage","First Reimage 2", "Functional Test", "Functional Test 2",
                              "Functional Test 3", "Final Reimage"]
        estaciones_values = ["FirstReimage-", "FirstReimage2-", "FunctionalTest-", "FunctionalTest2-",
                             "FunctionalTest3-", "FinalReimage-"]
        self.station_map = dict(zip(estaciones_display, estaciones_values))
        self.var_station.set(estaciones_values[0])
        self.create_option_group(self.tab_config, "Estación de Prueba:", 2, estaciones_display, self.var_station, command=self.select_station)

        # MODO
        mode_frame = ctk.CTkFrame(self.tab_config, fg_color="transparent")
        mode_frame.grid(row=3, column=0, pady=30, padx=20, sticky="ew")
        ctk.CTkLabel(mode_frame, text="Modo de Operación:", font=("Segoe UI", 14, "bold")).pack()
        self.mode_segmented = ctk.CTkSegmentedButton(mode_frame, values=["ONLINE", "OFFLINE"], variable=self.var_mode)
        self.mode_segmented.pack(fill="x", pady=5, padx=40)

        # BOTÓN PRINCIPAL
        ctk.CTkButton(
            self,
            text="▶️ POST Mapping",
            corner_radius=10,
            height=55,
            font=("Segoe UI", 16, "bold"),
            fg_color="#0078D4",
            hover_color="#005a9e",
            command=self.process
        ).pack(pady=(30, 20), padx=20, fill="x")

        # TAB MANTENIMIENTO
        ctk.CTkLabel(self.tab_maint, text="Opciones de Mantenimiento", font=("Segoe UI", 16)).pack(pady=20)
        ctk.CTkButton(
            self.tab_maint,
            text="🧽 Limpiar y Reorganizar CSV",
            height=40,
            corner_radius=8,
            fg_color="gray50",
            hover_color="gray30",
            command=self.confirmar_limpiar
        ).pack(padx=40, pady=(10, 5), fill="x")
        ctk.CTkLabel(self.tab_maint, text="Esta acción eliminará duplicados.", text_color="gray70").pack(pady=5)
        ctk.CTkButton(
            self.tab_maint,
            text="♻️ Restaurar Último Backup",
            height=40,
            corner_radius=8,
            fg_color="gray50",
            hover_color="gray30",
            command=self.confirmar_restaurar
        ).pack(padx=40, pady=(5, 20), fill="x")
        ctk.CTkLabel(self.tab_maint, text="Vista Previa de Datos Limpios (Solo Lectura):", font=("Segoe UI", 14, "bold")).pack(pady=(15, 5))
        self.csv_viewer = ctk.CTkTextbox(self.tab_maint, width=480, height=250, state="disabled", wrap="none", font=("Consolas", 10))
        self.csv_viewer.pack(padx=20, pady=(0, 20), fill="x", expand=True)

    # ============================================================
    # FUNCIONES AUXILIARES UI
    # ============================================================
    def resource_path(self, relative_path):
        """Obtiene la ruta absoluta del recurso (PyInstaller compatible)"""
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)

    def create_option_group(self, parent, label_text, row, values, variable, command=None):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, pady=20, padx=20, sticky="ew")
        ctk.CTkLabel(frame, text=label_text, font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        menu = ctk.CTkOptionMenu(frame, values=values, variable=variable, command=command)
        menu.grid(row=0, column=1, sticky="e")
        frame.columnconfigure(1, weight=1)
        return frame

    def select_station(self, display):
        self.var_station.set(self.station_map[display])

    # ============================================================
    # LIMPIEZA Y RESTAURAR CSV
    # ============================================================
    def confirmar_limpiar(self):
        if messagebox.askyesno("Confirmar limpieza", "¿Desea limpiar y reorganizar el CSV?\nEsta acción es irreversible."):
            self.limpiar_csv()

    def limpiar_csv(self):
        flag = self.var_flag.get()
        path = get_unc_path(flag)
        try:
            data = load_csv_server(path)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo leer el CSV: {e}")
            return
        new_data = limpiar_csv_data(data)
        try:
            save_csv_server(path, new_data, tipo="limpiar")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar el CSV reorganizado: {e}")
            return
        self.display_csv(new_data)
        messagebox.showinfo("Éxito", "CSV reorganizado y visualizado correctamente.")

    def confirmar_restaurar(self):
        flag = self.var_flag.get()
        path = get_unc_path(flag)
        if messagebox.askyesno("Confirmar restauración", "¿Desea restaurar el CSV desde el último backup?\nEsta acción sobrescribirá el archivo actual."):
            try:
                restore_backup_server(path)
                data = load_csv_server(path)
                self.display_csv(data)
                messagebox.showinfo("Éxito", "CSV restaurado desde backup correctamente.")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo restaurar el backup: {e}")

    # ============================================================
    # VISUALIZACIÓN CSV
    # ============================================================
    def display_csv(self, data):
        mac_width = 18
        full_width = 30
        formatted_text = ""
        for row in data:
            if not row or not any(row):
                formatted_text += "\n"
                continue
            is_record = len(row) > 1 and (str(row[1]).startswith('SUT_') or str(row[1]).startswith('SUL_'))
            if is_record:
                mac_val = str(row[0]).ljust(mac_width)
                full_val = str(row[1]).ljust(full_width)
                other_cols = " | ".join(str(c) for c in row[2:] if c)
                formatted_text += f"{mac_val}{full_val}{other_cols}\n"
            else:
                formatted_text += f"*** {str(row[0]).upper()} ***\n"
        self.csv_viewer.configure(state="normal")
        self.csv_viewer.delete("1.0", "end")
        self.csv_viewer.insert("1.0", formatted_text)
        self.csv_viewer.configure(state="disabled")
        self.csv_viewer.yview_moveto(0)

    # ============================================================
    # PROCESO PRINCIPAL
    # ============================================================
    def process(self):
        flag = self.var_flag.get()
        dev = self.var_device.get()
        station = self.var_station.get()
        mode = self.var_mode.get()

        if not dev or not station or not flag:
            messagebox.showerror("Error", "Debes seleccionar todas las opciones.")
            return

        path = get_unc_path(flag)
        try:
            data = load_csv_server(path)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo leer el CSV para el proceso de mapeo: {e}")
            return

        prefix = "SUT_" if dev == "Laptop" else "SUL_"
        mac = get_mac_address()
        if not mac:
            log_error("No se pudo detectar la MAC address (no se encontró adaptador válido)")
            messagebox.showerror("Error", "No se pudo detectar la MAC.")
            return

        duplicates = [row for row in data if row and row[0] == mac]
        if duplicates:
            text = "\n".join(",".join(row) for row in duplicates)
            msg = f"Se encontraron registros con la misma MAC:\n\n{text}\n\n¿Eliminar y reemplazar?"
            if not messagebox.askyesno("MAC duplicada", msg):
                return
            data = [row for row in data if not (row and row[0] == mac)]

        full = assign_ST(data, mac, prefix, station, mode)
        if full is None:
            messagebox.showerror("Error", "No hay ST disponibles en esta estación.")
            return

        data.append([mac, full] + [""] * 20)
        try:
            save_csv_server(path, data, tipo="registro")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar el registro en el servidor: {e}")
            return

        messagebox.showinfo("Éxito", f"Registro agregado:\n\nMAC: {mac}\nAsignación: {full}")

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        log_error("Fallo crítico al iniciar la aplicación", e)
