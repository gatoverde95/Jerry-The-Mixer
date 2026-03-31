import gi
import subprocess
import re
import threading

gi.require_version('Gtk', '3.0')
gi.require_version('Notify', '0.7')

try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3 as AppIndicator

from gi.repository import Gtk, Gdk, Notify, GLib

class JerryVM:
    def __init__(self):
        # 1. Identidad para evitar el "-c"
        GLib.set_prgname("JerryVM")
        GLib.set_application_name("JerryVM")
        
        self.app_name = "JerryVM"
        Notify.init(self.app_name)
        self.notification = Notify.Notification.new(self.app_name, "", "")
        
        self.current_vol = 0
        self.is_muted = False
        self.notify_timeout_id = None
        
        # 2. Inicialización del Indicador con un ID fresco
        # Usamos un ID genérico para que el panel no arrastre errores previos
        self.indicator = AppIndicator.Indicator.new(
            "jerryvm-audio-panel", 
            "audio-volume-high",
            AppIndicator.IndicatorCategory.SYSTEM_SERVICES
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        
        # 3. CONEXIÓN CRÍTICA: Conectar el scroll antes de armar el menú
        self.indicator.connect("scroll-event", self.on_scroll)
        
        # 4. UI y Menú
        self.menu = Gtk.Menu()
        self.create_menu_structure()
        self.indicator.set_menu(self.menu)

        # Sincronización con WirePlumber
        self.sync_with_wp()
        
        # Monitores en segundo plano
        threading.Thread(target=self.wp_monitor, daemon=True).start()
        GLib.timeout_add_seconds(3, self.update_media_info)

    def run_cmd(self, cmd):
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        except: return ""

    def sync_with_wp(self):
        out = self.run_cmd("wpctl get-volume @DEFAULT_AUDIO_SINK@")
        val = re.search(r"(\d\.\d+)", out)
        if val:
            self.current_vol = int(float(val.group(1)) * 100)
        self.is_muted = "[MUTED]" in out
        GLib.idle_add(self.update_ui_visuals)

    def wp_monitor(self):
        proc = subprocess.Popen(["pw-mon"], stdout=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if "changed" in line:
                GLib.idle_add(self.sync_with_wp)

    def create_menu_structure(self):
        self.header_item = Gtk.MenuItem(label=" JerryVM - Control")
        self.header_item.set_sensitive(False)
        self.menu.append(self.header_item)
        self.menu.append(Gtk.SeparatorMenuItem())
        
        item_jerry = Gtk.MenuItem(label="Abrir Jerry The Mixer")
        item_jerry.connect("activate", lambda w: subprocess.Popen(["jerry-the-mixer"]))
        self.menu.append(item_jerry)
        self.menu.append(Gtk.SeparatorMenuItem())
        
        self.track_item = Gtk.MenuItem(label="  Sin música")
        self.track_item.set_sensitive(False)
        self.menu.append(self.track_item)
        
        item_play = Gtk.MenuItem(label="Reproducir / Pausar")
        item_play.connect("activate", lambda w: subprocess.Popen(["playerctl", "play-pause"]))
        self.menu.append(item_play)
        
        self.menu.append(Gtk.SeparatorMenuItem())
        self.mute_item = Gtk.CheckMenuItem(label="Silenciar (Mute)")
        self.mute_handler_id = self.mute_item.connect("toggled", self.on_mute_toggled)
        self.menu.append(self.mute_item)
        
        item_exit = Gtk.MenuItem(label="Cerrar JerryVM")
        item_exit.connect("activate", lambda w: Gtk.main_quit())
        self.menu.append(item_exit)
        self.menu.show_all()

    def update_ui_visuals(self):
        vol, muted = self.current_vol, self.is_muted
        
        if muted or vol == 0: icon = "audio-volume-muted"
        elif vol < 30: icon = "audio-volume-low"
        elif vol < 70: icon = "audio-volume-medium"
        else: icon = "audio-volume-high"
        
        # Actualizamos el icono
        self.indicator.set_icon_full(icon, "")
        
        # Actualizamos la ETIQUETA (El porcentaje al lado del icono)
        label_text = f" {vol}%" if not muted else " MUTE"
        self.indicator.set_label(label_text, "JerryVM")
        
        # Actualizamos el primer item del menú
        self.header_item.set_label(f" JerryVM - {label_text.strip()}")
        
        self.mute_item.handler_block(self.mute_handler_id)
        self.mute_item.set_active(muted)
        self.mute_item.handler_unblock(self.mute_handler_id)

    def update_media_info(self):
        def fetch():
            track = self.run_cmd("playerctl metadata title")
            if track:
                display = (track[:22] + '..') if len(track) > 22 else track
                GLib.idle_add(self.track_item.set_label, f"  {display}")
                GLib.idle_add(self.track_item.show)
            else:
                GLib.idle_add(self.track_item.hide)
        threading.Thread(target=fetch, daemon=True).start()
        return True

    def on_scroll(self, indicator, steps, direction):
        # Acción inmediata para PipeWire
        op = "2%+" if direction == Gdk.ScrollDirection.UP else "2%-"
        subprocess.Popen(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", op])
        
        # Predicción visual para 0 lag
        if direction == Gdk.ScrollDirection.UP:
            self.current_vol = min(130, self.current_vol + 2)
        else:
            self.current_vol = max(0, self.current_vol - 2)
            
        self.update_ui_visuals()
        
        # Debounce para la notificación
        if self.notify_timeout_id: GLib.source_remove(self.notify_timeout_id)
        self.notify_timeout_id = GLib.timeout_add(100, self.show_fast_notify)

    def show_fast_notify(self):
        self.notification.update("Volumen", f"Nivel: {self.current_vol}%", "audio-speakers")
        self.notification.show()
        self.notify_timeout_id = None
        return False

    def on_mute_toggled(self, widget):
        subprocess.Popen(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])

if __name__ == "__main__":
    app = JerryVM()
    Gtk.main()