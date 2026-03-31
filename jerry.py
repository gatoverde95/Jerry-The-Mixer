#!/usr/bin/env python3
"""
Jerry The Mixer  v0.5
Mezclador compacto PulseAudio/PipeWire — GTK3 nativo sin CSS
Pestañas: Salidas | Entradas | General
Configuración: ~/.config/jerry-mixer/config.ini
Iconos SVG: jerry.svg (app), jerry_about.svg (about)
Requiere: python3-gi  gir1.2-gtk-3.0  pulseaudio-utils  pavucontrol
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf

import subprocess, json, sys, signal, os, configparser, threading, functools

# ═══════════════════════════════════════════════════════════════════════
#  Rutas de recursos  (SVGs junto al script)
# ═══════════════════════════════════════════════════════════════════════

_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SVG_APP      = os.path.join(_SCRIPT_DIR, 'jerry.svg')
SVG_ABOUT    = os.path.join(_SCRIPT_DIR, 'jerry_about.svg')
CONFIG_PATH  = os.path.expanduser('~/.config/jerry-mixer/config.ini')

ICON_SIZE    = Gtk.IconSize.SMALL_TOOLBAR   # 16 px

APP_VERSION  = '0.5'
APP_NAME     = 'Jerry The Mixer'
APP_COMMENT  = 'Mezclador de audio PulseAudio/PipeWire'
APP_WEBSITE  = 'https://cuerdos.github.io'


# ═══════════════════════════════════════════════════════════════════════
#  Configuración  (~/.config/jerry-mixer/config.ini)
# ═══════════════════════════════════════════════════════════════════════

class Config:
    DEFAULTS = {
        'refresh_interval': '2500',
        'audio_type':       'auto',
        'show_apps':        'true',
        'show_monitors':    'false',
        'show_src_outputs': 'true',
    }

    def __init__(self):
        self._cp = configparser.ConfigParser()
        self._cp['jerry'] = dict(self.DEFAULTS)
        self._load()

    def _load(self):
        if os.path.exists(CONFIG_PATH):
            self._cp.read(CONFIG_PATH)

    def save(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            self._cp.write(f)

    def _s(self, key):
        return self._cp.get('jerry', key, fallback=self.DEFAULTS[key])

    @property
    def refresh_interval(self):
        try:    return max(500, int(self._s('refresh_interval')))
        except: return 2500

    @refresh_interval.setter
    def refresh_interval(self, v):
        self._cp['jerry']['refresh_interval'] = str(int(v))

    @property
    def audio_type(self):
        return self._s('audio_type')

    @audio_type.setter
    def audio_type(self, v):
        self._cp['jerry']['audio_type'] = v

    @property
    def show_apps(self):
        return self._s('show_apps').lower() == 'true'

    @show_apps.setter
    def show_apps(self, v):
        self._cp['jerry']['show_apps'] = 'true' if v else 'false'

    @property
    def show_monitors(self):
        return self._s('show_monitors').lower() == 'true'

    @show_monitors.setter
    def show_monitors(self, v):
        self._cp['jerry']['show_monitors'] = 'true' if v else 'false'

    @property
    def show_src_outputs(self):
        return self._s('show_src_outputs').lower() == 'true'

    @show_src_outputs.setter
    def show_src_outputs(self, v):
        self._cp['jerry']['show_src_outputs'] = 'true' if v else 'false'


# ═══════════════════════════════════════════════════════════════════════
#  pactl helpers
# ═══════════════════════════════════════════════════════════════════════

def pactl_json(*args):
    try:
        r = subprocess.run(
            ['pactl', '--format=json'] + list(args),
            capture_output=True, text=True, timeout=4)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except Exception:
        pass
    return None

def pactl_cmd(*args):
    try:
        return subprocess.run(
            ['pactl'] + list(args),
            capture_output=True, text=True, timeout=4
        ).returncode == 0
    except Exception:
        return False

def vol_pct(vol_obj):
    if isinstance(vol_obj, dict):
        for ch in vol_obj.values():
            if isinstance(ch, dict):
                try:
                    return int(str(ch.get('value_percent', '100'))
                               .replace('%', '').strip())
                except ValueError:
                    pass
    return 100

def detect_audio_server():
    try:
        info = pactl_json('info') or {}
        server = info.get('server_name', '') or ''
        if 'pipewire' in server.lower():
            return 'PipeWire'
        if 'pulseaudio' in server.lower():
            return 'PulseAudio'
        version = info.get('server_version', '')
        return f'Servidor de audio ({version})' if version else 'Desconocido'
    except Exception:
        return 'Desconocido'


# ═══════════════════════════════════════════════════════════════════════
#  Nombres legibles
# ═══════════════════════════════════════════════════════════════════════

def device_display_name(obj: dict) -> str:
    props = obj.get('properties') or {}
    candidates = [
        props.get('device.description'),
        props.get('node.description'),
        props.get('node.nick'),
        props.get('device.product.name'),
        obj.get('description'),
        props.get('alsa.card_name'),
        props.get('alsa.long_card_name'),
        props.get('device.alias'),
    ]
    for c in candidates:
        if c and isinstance(c, str) and c.strip():
            return c.strip()
    return _clean_raw_name(obj.get('name', '') or '')

def app_display_name(props: dict, fallback: str) -> str:
    for key in ('application.name', 'media.name',
                'node.description', 'node.nick', 'node.name'):
        v = props.get(key, '')
        if v and isinstance(v, str):
            return v.strip()
    return fallback

def _clean_raw_name(raw: str) -> str:
    n = raw
    for pfx in ('alsa_output.', 'alsa_input.', 'bluez_output.',
                'bluez_input.',  'bluez_sink.',  'bluez_source.',
                'v4l2_input.', 'jack-', 'pipewire-'):
        if n.startswith(pfx):
            n = n[len(pfx):]
            break
    for sfx in ('.analog-stereo', '.analog-mono', '.iec958-stereo',
                '.hdmi-stereo', '.hdmi-surround', '.a2dp-sink',
                '.headset-head-unit', '.handsfree-head-unit'):
        if n.endswith(sfx):
            n = n[:-len(sfx)]
            break
    n = n.replace('_', ' ').replace('.', ' ').replace('-', ' ')
    parts = [p.capitalize() for p in n.split()
             if not (len(p) <= 4 and
                     all(c in '0123456789abcdefABCDEF' for c in p))]
    return ' '.join(parts) if parts else raw

def trunc(s, n=30):
    if not s: return '—'
    return s if len(s) <= n else s[:n-1] + '…'


# ═══════════════════════════════════════════════════════════════════════
#  Utilidades GTK
# ═══════════════════════════════════════════════════════════════════════

@functools.lru_cache(maxsize=16)
def _svg_pixbuf(path, size=24):
    """Carga un SVG como pixbuf escalado (con caché)."""
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
    except Exception:
        return None

def icon_image(name, fallback='audio-x-generic', size=ICON_SIZE):
    theme = Gtk.IconTheme.get_default()
    for n in (name, fallback, 'image-missing'):
        if theme.has_icon(n):
            return Gtk.Image.new_from_icon_name(n, size)
    return Gtk.Image()

def app_icon_image(size=32):
    pb = _svg_pixbuf(SVG_APP, size)
    if pb:
        return Gtk.Image.new_from_pixbuf(pb)
    return icon_image('multimedia-volume-control', 'audio-x-generic',
                      Gtk.IconSize.LARGE_TOOLBAR)

def bold_label(text, scale=1.0, color=None):
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(0)
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
    if scale != 1.0:
        attrs.insert(Pango.attr_scale_new(scale))
    if color:
        r, g, b = color
        attrs.insert(Pango.attr_foreground_new(r*257, g*257, b*257))
    lbl.set_attributes(attrs)
    return lbl

def small_label(text, color=None):
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(0)
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_scale_new(0.82))
    if color:
        r, g, b = color
        attrs.insert(Pango.attr_foreground_new(r*257, g*257, b*257))
    lbl.set_attributes(attrs)
    return lbl

def set_label_color(lbl, color, scale=0.82):
    r, g, b = color
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_foreground_new(r*257, g*257, b*257))
    attrs.insert(Pango.attr_scale_new(scale))
    lbl.set_attributes(attrs)

def _menu_item_with_icon(label_text, icon_name):
    """MenuItem con icono del tema GTK — sin emojis."""
    item = Gtk.MenuItem()
    box  = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.pack_start(icon_image(icon_name, 'image-missing', Gtk.IconSize.MENU),
                   False, False, 0)
    lbl = Gtk.Label(label=label_text)
    lbl.set_xalign(0)
    box.pack_start(lbl, True, True, 0)
    box.show_all()
    item.add(box)
    return item

# Paleta
C_SINK    = (60,  150, 220)
C_SOURCE  = (210, 120,  30)
C_APP     = (150, 100, 210)
C_GEN_OUT = (40,  180, 100)
C_GEN_IN  = (190, 170,  30)
C_MUTED   = (190,  50,  50)
C_DIM     = (120, 120, 120)
C_OK      = (50,  180,  80)


# ═══════════════════════════════════════════════════════════════════════
#  ChannelRow
# ═══════════════════════════════════════════════════════════════════════

class ChannelRow(Gtk.Box):
    def __init__(self, kind, index, label, volume, muted, on_vol, on_mute,
                 on_interact_start=None, on_interact_end=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.set_border_width(2)
        self.kind              = kind
        self.index             = index
        self._on_vol           = on_vol
        self._on_mute          = on_mute
        self._on_interact_start = on_interact_start
        self._on_interact_end   = on_interact_end
        self._busy             = False
        self._vol_timer        = None

        color = {
            'sink':    C_SINK,   'gen-out': C_GEN_OUT,
            'source':  C_SOURCE, 'gen-in':  C_GEN_IN,
            'app':     C_APP,    'srcout':  C_SOURCE,
        }.get(kind, C_DIM)

        self.mute_btn = Gtk.Button()
        self.mute_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.mute_btn.set_focus_on_click(False)
        self.mute_btn.set_tooltip_text('Silenciar / Activar sonido  (clic)')
        self.mute_btn.connect('clicked',
            lambda w: self._on_mute(self.kind, self.index))
        self.pack_start(self.mute_btn, False, False, 0)

        self.name_lbl = small_label(trunc(label, 20), color=color)
        self.name_lbl.set_max_width_chars(18)
        self.pack_start(self.name_lbl, False, False, 0)

        adj = Gtk.Adjustment(value=volume, lower=0, upper=153,
                             step_increment=1, page_increment=5)
        self.slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL,
                                adjustment=adj)
        self.slider.set_draw_value(False)
        self.slider.set_hexpand(True)
        self.slider.set_size_request(100, -1)
        self.slider.set_tooltip_text(
            'Arrastra para cambiar el volumen\n'
            'También puedes usar la rueda del ratón')
        self.slider.connect('value-changed', self._on_slider)
        # Interceptar scroll antes de que GTK/ScrolledWindow lo amplifique
        self.slider.add_events(Gdk.EventMask.SCROLL_MASK |
                               Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.slider.connect('scroll-event', self._on_slider_scroll)
        self.pack_start(self.slider, True, True, 0)

        self.pct_lbl = Gtk.Label()
        self.pct_lbl.set_width_chars(5)
        self.pct_lbl.set_xalign(1.0)
        self.pct_lbl.override_font(Pango.FontDescription('Monospace 8'))
        self.pack_start(self.pct_lbl, False, False, 0)

        self.update_state(volume, muted)

    def update_state(self, volume, muted):
        self._busy = True
        self.slider.set_value(volume)
        child = self.mute_btn.get_child()
        if child:
            self.mute_btn.remove(child)
        if muted:
            self.mute_btn.add(icon_image('audio-volume-muted',
                                         'audio-volume-muted'))
            set_label_color(self.pct_lbl, C_MUTED)
            self.pct_lbl.set_text('MUTE')
        else:
            self.mute_btn.add(icon_image('audio-volume-high',
                                         'audio-volume-high'))
            set_label_color(self.pct_lbl, C_OK)
            self.pct_lbl.set_text(f'{int(volume)}%')
        self.mute_btn.show_all()
        self._busy = False

    def _on_slider_scroll(self, widget, event):
        # Scroll controlado: 5 pasos por tick, sin saltos,
        # return True detiene la propagacion al ScrolledWindow.
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dx, dy = event.get_scroll_deltas()
            step = -1 if dy > 0 else (1 if dy < 0 else 0)
        elif event.direction == Gdk.ScrollDirection.UP:
            step = 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            step = -1
        else:
            return False
        # Notificar inicio de interacción (suprime rebuild externo)
        if self._on_interact_start:
            self._on_interact_start()
        cur = self.slider.get_value()
        new_val = max(0, min(153, cur + step * 5))
        self._busy = True
        self.slider.set_value(new_val)
        self._busy = False
        self.pct_lbl.set_text(f'{int(new_val)}%')
        if self._vol_timer:
            GLib.source_remove(self._vol_timer)
        # Al acabar el debounce: enviar volumen y liberar bloqueo
        self._vol_timer = GLib.timeout_add(80, self._send_vol_and_release, int(new_val))
        return True

    def _on_slider(self, w):
        if self._busy: return
        val = int(w.get_value())
        self.pct_lbl.set_text(f'{val}%')
        if self._vol_timer:
            GLib.source_remove(self._vol_timer)
        self._vol_timer = GLib.timeout_add(80, self._send_vol, val)

    def _send_vol(self, val):
        self._vol_timer = None
        threading.Thread(
            target=self._on_vol, args=(self.kind, self.index, val),
            daemon=True).start()
        return False

    def _send_vol_and_release(self, val):
        """Como _send_vol pero además libera el bloqueo de interaccion."""
        self._vol_timer = None
        threading.Thread(
            target=self._on_vol, args=(self.kind, self.index, val),
            daemon=True).start()
        if self._on_interact_end:
            # Pequeño delay extra para que pactl procese antes del siguiente refresh
            GLib.timeout_add(400, self._on_interact_end)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  DeviceBlock
# ═══════════════════════════════════════════════════════════════════════

def _sink_icon(name):
    n = name.lower()
    if any(x in n for x in ('headphone', 'headset', 'auricular')):
        return 'audio-headphones'
    if any(x in n for x in ('bluetooth', 'bluez', 'a2dp')):
        return 'bluetooth-audio'
    if any(x in n for x in ('hdmi', 'display', 'monitor')):
        return 'video-display'
    return 'audio-speakers'

def _source_icon(name):
    n = name.lower()
    if any(x in n for x in ('bluetooth', 'bluez', 'headset')):
        return 'bluetooth-audio'
    if any(x in n for x in ('webcam', 'camera', 'video')):
        return 'camera-web'
    return 'audio-input-microphone'

class DeviceBlock(Gtk.Frame):
    def __init__(self, kind, index, display_name, volume, muted,
                 on_vol, on_mute,
                 on_interact_start=None, on_interact_end=None):
        super().__init__()
        self.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.set_border_width(3)
        self.kind  = kind
        self.index = index

        icon_n = (_sink_icon(display_name)
                  if kind in ('sink', 'gen-out')
                  else _source_icon(display_name))

        color = {
            'sink': C_SINK, 'source': C_SOURCE,
            'gen-out': C_GEN_OUT, 'gen-in': C_GEN_IN,
        }.get(kind, C_DIM)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        title_box.pack_start(
            icon_image(icon_n, 'audio-card'), False, False, 0)
        title_lbl = bold_label(trunc(display_name, 28), scale=0.95, color=color)
        title_lbl.set_max_width_chars(26)
        title_box.pack_start(title_lbl, False, False, 0)
        title_box.show_all()
        self.set_label_widget(title_box)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        inner.set_border_width(4)
        self.add(inner)

        self.row = ChannelRow(kind, index, 'Volumen',
                              volume, muted, on_vol, on_mute,
                              on_interact_start, on_interact_end)
        inner.pack_start(self.row, False, False, 0)

    def update_state(self, vol, muted):
        self.row.update_state(vol, muted)


# ═══════════════════════════════════════════════════════════════════════
#  DeviceSelector
# ═══════════════════════════════════════════════════════════════════════

class DeviceSelector(Gtk.Box):
    def __init__(self, kind, on_refresh=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.set_border_width(4)
        self.kind        = kind
        self._items      = []    # nombres raw en el mismo orden que el store
        self._sig_id     = None  # id de señal 'changed' (para bloquearla)
        self._on_refresh = on_refresh

        icon_n = ('audio-speakers'
                  if kind == 'sink' else 'audio-input-microphone')
        self.pack_start(
            icon_image(icon_n, 'audio-card', Gtk.IconSize.BUTTON),
            False, False, 0)

        self.store = Gtk.ListStore(str, str)
        self.combo = Gtk.ComboBox.new_with_model(self.store)
        renderer  = Gtk.CellRendererText()
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        renderer.set_property('max-width-chars', 26)
        self.combo.pack_start(renderer, True)
        self.combo.add_attribute(renderer, 'text', 0)
        self.combo.set_hexpand(True)
        self.combo.set_tooltip_text(
            'Selecciona el dispositivo y pulsa ✓ para aplicarlo como predeterminado')
        self.pack_start(self.combo, True, True, 0)

        # Botón Aplicar: solo icono, sin texto ni emojis
        btn = Gtk.Button()
        btn.set_image(icon_image('emblem-default', 'dialog-apply',
                                 Gtk.IconSize.BUTTON))
        btn.set_tooltip_text(
            'Establecer como dispositivo por defecto\n'
            'El sistema usará este dispositivo para nuevo audio')
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.connect('clicked', self._on_apply)
        self.pack_start(btn, False, False, 0)

    # ── Conexión única de la señal 'changed' ─────────────────────────

    def _ensure_sig(self):
        if self._sig_id is None:
            self._sig_id = self.combo.connect('changed', lambda *_: None)

    # ── populate ─────────────────────────────────────────────────────

    def populate(self, devices, current_name):
        """Actualiza el combo de forma eficiente:
        • Si la lista no cambió, solo corrige la selección si no hay una
          activa (primer arranque o reset externo).
        • Si cambió, reconstruye bloqueando la señal 'changed' para evitar
          cualquier redibujado parcial (fuente del parpadeo).
        """
        new_names = [d.get('name', '') for d in devices]

        # ── Sin cambios estructurales: tocar lo mínimo
        if new_names == self._items:
            if self.combo.get_active() < 0 and self._items:
                target = (self._items.index(current_name)
                          if current_name in self._items else 0)
                self._set_active_silent(target)
            return

        # ── Lista cambió: guardar selección del usuario y reconstruir
        cur_idx  = self.combo.get_active()
        user_sel = (self._items[cur_idx]
                    if 0 <= cur_idx < len(self._items) else None)

        self._ensure_sig()
        self.combo.handler_block(self._sig_id)
        try:
            self.store.clear()
            self._items    = []
            default_active = 0
            for i, d in enumerate(devices):
                raw  = d.get('name', '')
                disp = device_display_name(d)
                self.store.append([disp, raw])
                self._items.append(raw)
                if raw == current_name:
                    default_active = i
        finally:
            self.combo.handler_unblock(self._sig_id)

        if not self._items:
            return

        # Prioridad: selección previa del usuario > default actual del sistema
        target = (self._items.index(user_sel)
                  if user_sel and user_sel in self._items
                  else default_active)
        self._set_active_silent(target)

    def _set_active_silent(self, idx):
        """set_active() sin disparar señales externas."""
        self._ensure_sig()
        self.combo.handler_block(self._sig_id)
        self.combo.set_active(idx)
        self.combo.handler_unblock(self._sig_id)

    def _on_apply(self, _w):
        idx = self.combo.get_active()
        if not (0 <= idx < len(self._items)):
            return
        cmd  = ('set-default-sink' if self.kind == 'sink'
                else 'set-default-source')
        name = self._items[idx]
        def _do():
            pactl_cmd(cmd, name)
            if self._on_refresh:
                GLib.timeout_add(300, self._on_refresh)
        threading.Thread(target=_do, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
#  Diálogo de Configuración
# ═══════════════════════════════════════════════════════════════════════

class ConfigDialog(Gtk.Dialog):
    def __init__(self, parent, cfg: Config):
        super().__init__(title='Configuración — Jerry The Mixer',
                         transient_for=parent,
                         modal=True,
                         destroy_with_parent=True)
        self.set_border_width(8)
        self.set_resizable(False)
        self._cfg = cfg

        self.add_button('Cancelar', Gtk.ResponseType.CANCEL)
        ok_btn = self.add_button('Guardar', Gtk.ResponseType.OK)
        ok_btn.get_style_context().add_class('suggested-action')

        box = self.get_content_area()
        box.set_spacing(8)

        # ── Sección: Servidor de audio ───────────────────────────────
        box.pack_start(self._section_title('Tipo de Servidor de Audio',
                                           'audio-card'),
                       False, False, 4)

        detected = detect_audio_server()
        det_lbl  = Gtk.Label(label=f'Detectado: {detected}')
        det_lbl.set_xalign(0)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_scale_new(0.85))
        attrs.insert(Pango.attr_style_new(Pango.Style.ITALIC))
        det_lbl.set_attributes(attrs)
        box.pack_start(det_lbl, False, False, 0)

        at_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        at_box.pack_start(Gtk.Label(label='Forzar servidor:'), False, False, 0)

        self.audio_type_combo = Gtk.ComboBoxText()
        for val, label in [('auto',       'Automático (recomendado)'),
                            ('pulseaudio', 'PulseAudio clásico'),
                            ('pipewire',   'PipeWire')]:
            self.audio_type_combo.append(val, label)
        self.audio_type_combo.set_active_id(cfg.audio_type)
        at_box.pack_start(self.audio_type_combo, True, True, 0)
        box.pack_start(at_box, False, False, 0)

        box.pack_start(Gtk.Separator(
            orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # ── Sección: Refresco ────────────────────────────────────────
        box.pack_start(self._section_title('Intervalo de Refresco',
                                           'view-refresh'),
                       False, False, 4)

        ref_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ref_box.pack_start(Gtk.Label(label='Cada:'), False, False, 0)
        adj = Gtk.Adjustment(value=cfg.refresh_interval / 1000.0,
                             lower=0.5, upper=30.0,
                             step_increment=0.5, page_increment=1.0)
        self.refresh_spin = Gtk.SpinButton(adjustment=adj, digits=1)
        ref_box.pack_start(self.refresh_spin, False, False, 0)
        ref_box.pack_start(Gtk.Label(label='segundos'), False, False, 0)
        box.pack_start(ref_box, False, False, 0)

        box.pack_start(Gtk.Separator(
            orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        # ── Sección: Visibilidad ─────────────────────────────────────
        box.pack_start(self._section_title('Mostrar / Ocultar Secciones',
                                           'preferences-system'),
                       False, False, 4)

        self.chk_apps = Gtk.CheckButton(
            label='Mostrar aplicaciones reproduciendo audio')
        self.chk_apps.set_active(cfg.show_apps)
        box.pack_start(self.chk_apps, False, False, 0)

        self.chk_monitors = Gtk.CheckButton(
            label='Mostrar entradas de monitoreo (loopback)')
        self.chk_monitors.set_active(cfg.show_monitors)
        box.pack_start(self.chk_monitors, False, False, 0)

        self.chk_srcout = Gtk.CheckButton(
            label='Mostrar aplicaciones grabando audio')
        self.chk_srcout.set_active(cfg.show_src_outputs)
        box.pack_start(self.chk_srcout, False, False, 0)

        box.show_all()

    def _section_title(self, text, icon_name=None):
        """Título de sección con icono GTK — sin emojis."""
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if icon_name:
            hbox.pack_start(
                icon_image(icon_name, 'image-missing',
                           Gtk.IconSize.SMALL_TOOLBAR),
                False, False, 0)
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        lbl.set_attributes(attrs)
        hbox.pack_start(lbl, True, True, 0)
        return hbox

    def apply_to(self, cfg: Config):
        cfg.audio_type       = self.audio_type_combo.get_active_id() or 'auto'
        cfg.refresh_interval = int(self.refresh_spin.get_value() * 1000)
        cfg.show_apps        = self.chk_apps.get_active()
        cfg.show_monitors    = self.chk_monitors.get_active()
        cfg.show_src_outputs = self.chk_srcout.get_active()
        cfg.save()


# ═══════════════════════════════════════════════════════════════════════
#  Acerca de  (estándar GTK AboutDialog + GPL-3.0)
# ═══════════════════════════════════════════════════════════════════════

def build_about_dialog(parent):
    dlg = Gtk.AboutDialog()
    dlg.set_transient_for(parent)
    dlg.set_modal(True)
    dlg.set_destroy_with_parent(True)
    dlg.set_program_name(APP_NAME)
    dlg.set_version(APP_VERSION)
    dlg.set_comments(APP_COMMENT)
    dlg.set_website(APP_WEBSITE)
    dlg.set_website_label('Pagina Web')
    dlg.set_copyright('🄯 2026 CuerdOS')
    dlg.set_license_type(Gtk.License.GPL_3_0)
    pb = _svg_pixbuf(SVG_ABOUT, 96) or _svg_pixbuf(SVG_APP, 96)
    if pb:
        dlg.set_logo(pb)
    return dlg


# ═══════════════════════════════════════════════════════════════════════
#  Ventana principal
# ═══════════════════════════════════════════════════════════════════════

class JerryMixer(Gtk.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(False)
        self.set_skip_pager_hint(False)
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_default_size(430, -1)
        self.set_border_width(0)

        pb = _svg_pixbuf(SVG_APP, 64)
        if pb:
            self.set_icon(pb)

        self._cfg      = Config()
        self._dragging = False
        self._drag_x   = self._drag_y = 0
        self._blocks   = {}
        self._timer_id = None
        self._loading  = False
        self._first_show = True   # show_all() solo la primera vez
        self._user_interacting = False  # True mientras el usuario arrastra/scrollea

        self._build_ui()
        self._load_audio()
        self._schedule_refresh()
        # Monitor de eventos en tiempo real (reacciona a cambios externos)
        threading.Thread(target=self._pactl_monitor, daemon=True).start()

        self.connect('delete-event', lambda *_: self.destroy())
        self.connect('button-press-event',   self._drag_press)
        self.connect('button-release-event', self._drag_release)
        self.connect('motion-notify-event',  self._drag_motion)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK   |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK)

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        # Barra de título
        titlebar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        titlebar.set_border_width(5)
        titlebar.pack_start(app_icon_image(28), False, False, 2)

        title = Gtk.Label()
        title.set_markup(f'<b>{APP_NAME}</b>')
        title.set_xalign(0)
        titlebar.pack_start(title, True, True, 0)

        pavu_btn = Gtk.Button(label='pavucontrol')
        pavu_btn.set_image(icon_image('preferences-desktop',
                                      'system-run', Gtk.IconSize.BUTTON))
        pavu_btn.set_always_show_image(True)
        pavu_btn.set_relief(Gtk.ReliefStyle.NORMAL)
        pavu_btn.set_focus_on_click(False)
        pavu_btn.set_tooltip_text(
            'Abrir PulseAudio Volume Control\n'
            'Control avanzado de audio con más opciones')
        pavu_btn.connect('clicked', self._open_pavucontrol)
        titlebar.pack_start(pavu_btn, False, False, 0)

        # Menú: icono del tema en vez de emoji ☰
        menu_btn = Gtk.MenuButton()
        menu_btn.set_image(icon_image('open-menu-symbolic',
                                      'application-menu', Gtk.IconSize.BUTTON))
        menu_btn.set_relief(Gtk.ReliefStyle.NONE)
        menu_btn.set_focus_on_click(False)
        menu_btn.set_tooltip_text('Menú — Configuración, recargar y más')
        menu_btn.set_popup(self._build_menu())
        titlebar.pack_start(menu_btn, False, False, 0)

        root.pack_start(titlebar, False, False, 0)
        root.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 0)

        self.nb = Gtk.Notebook()
        self.nb.set_tab_pos(Gtk.PositionType.TOP)
        root.pack_start(self.nb, True, True, 0)

        self.tab_out = self._make_tab('audio-speakers',         'Salidas',
            'Altavoces, auriculares y otros dispositivos de salida')
        self.tab_in  = self._make_tab('audio-input-microphone', 'Entradas',
            'Micrófonos y otras fuentes de captura de audio')
        self.tab_gen = self._make_tab('preferences-system',     'General',
            'Vista rápida: dispositivo principal y aplicaciones activas')

        # Selectores creados UNA SOLA VEZ en la zona fija (sobreviven a refreshes)
        self._section_label(self.tab_out, 'Dispositivo de salida predeterminado',
                            'audio-speakers', C_SINK, fixed=True)
        self.sel_sink = DeviceSelector('sink', on_refresh=self._load_audio)
        self.tab_out['fixed'].pack_start(self.sel_sink, False, False, 0)

        self._section_label(self.tab_in, 'Dispositivo de entrada predeterminado',
                            'audio-input-microphone', C_SOURCE, fixed=True)
        self.sel_source = DeviceSelector('source', on_refresh=self._load_audio)
        self.tab_in['fixed'].pack_start(self.sel_source, False, False, 0)

        root.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 0)
        sbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        sbar.set_border_width(3)
        self.status_lbl = Gtk.Label(label='Iniciando…')
        self.status_lbl.modify_font(Pango.FontDescription('Monospace 7'))
        self.status_lbl.set_xalign(0)
        sbar.pack_start(self.status_lbl, True, True, 4)
        root.pack_start(sbar, False, False, 0)

    def _build_menu(self):
        """Menú con iconos GTK — sin emojis."""
        menu = Gtk.Menu()

        item_cfg = _menu_item_with_icon('Configuración…', 'preferences-system')
        item_cfg.connect('activate', self._open_config)
        menu.append(item_cfg)

        item_reload = _menu_item_with_icon('Recargar ahora', 'view-refresh')
        item_reload.connect('activate', lambda w: self._load_audio())
        menu.append(item_reload)

        menu.append(Gtk.SeparatorMenuItem())

        item_about = _menu_item_with_icon('Acerca de Jerry…', 'help-about')
        item_about.connect('activate', self._open_about)
        menu.append(item_about)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = _menu_item_with_icon('Salir', 'application-exit')
        item_quit.connect('activate', lambda w: Gtk.main_quit())
        menu.append(item_quit)

        menu.show_all()
        return menu

    def _make_tab(self, icon_name, label_text, tooltip=None):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(60)
        scroll.set_max_content_height(420)
        scroll.set_propagate_natural_height(True)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root_box.set_border_width(6)
        scroll.add(root_box)

        # Zona FIJA: selector de dispositivo por defecto (nunca se borra)
        fixed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        root_box.pack_start(fixed_box, False, False, 0)

        root_box.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 2)

        # Zona DINÁMICA: bloques de dispositivos/apps (se recrea en cada refresh)
        dyn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        root_box.pack_start(dyn_box, True, True, 0)

        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tab_box.pack_start(
            icon_image(icon_name, 'audio-x-generic', ICON_SIZE),
            False, False, 0)
        tab_box.pack_start(Gtk.Label(label=label_text), False, False, 0)
        if tooltip:
            tab_box.set_tooltip_text(tooltip)
        tab_box.show_all()

        self.nb.append_page(scroll, tab_box)
        return {'scroll': scroll, 'fixed': fixed_box, 'box': dyn_box}

    def _clear_tab(self, tab):
        """Solo borra la zona dinámica — los selectores en 'fixed' sobreviven."""
        for ch in list(tab['box'].get_children()):
            tab['box'].remove(ch)

    def _sep(self, tab):
        tab['box'].pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 2)

    def _section_label(self, tab, text, icon_name=None, color=C_DIM, fixed=False):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_top(4)
        if icon_name:
            row.pack_start(icon_image(icon_name, 'audio-x-generic',
                                      ICON_SIZE), False, False, 0)
        row.pack_start(bold_label(text, scale=0.88, color=color),
                       False, False, 0)
        target = tab['fixed'] if fixed else tab['box']
        target.pack_start(row, False, False, 0)

    # ── Monitor de eventos PulseAudio/PipeWire ────────────────────────

    def _pactl_monitor(self):
        """Escucha 'pactl subscribe' y dispara un refresh cuando cambia algo
        relevante. Usa debounce de 300 ms para no saturar con ráfagas de eventos."""
        import time
        RELEVANT_OBJECTS = {"sink", "source", "server", "sink-input", "source-output"}
        RELEVANT_EVENTS  = {"'change'", "'new'", "'remove'"}
        _pending = [False]

        def _schedule():
            if not _pending[0]:
                _pending[0] = True
                GLib.timeout_add(300, _do_refresh)

        def _do_refresh():
            _pending[0] = False
            # No reconstruir widgets mientras el usuario está scrolleando/arrastrando
            if not self._user_interacting:
                self._load_audio()
            return False

        while True:
            try:
                proc = subprocess.Popen(
                    ['pactl', 'subscribe'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
                )
                for line in proc.stdout:
                    low = line.lower()
                    if any(obj in low for obj in RELEVANT_OBJECTS):
                        if any(ev in low for ev in RELEVANT_EVENTS):
                            GLib.idle_add(_schedule)
                proc.wait()
            except Exception:
                pass
            time.sleep(2)  # reintentar si el proceso muere

    # ── Timer de refresco ─────────────────────────────────────────────

    def _schedule_refresh(self):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add(
            self._cfg.refresh_interval, self._auto_refresh)

    def _auto_refresh(self):
        self._load_audio()
        return True

    # ── Carga de audio ────────────────────────────────────────────────

    def _load_audio(self):
        if self._loading:
            return
        self._loading = True
        # Reiniciar el timer para que no duplique el refresh del monitor
        self._schedule_refresh()
        threading.Thread(target=self._fetch_audio_data, daemon=True).start()

    def _fetch_audio_data(self):
        """Obtiene todos los datos de audio en paralelo para reducir la latencia."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        queries = {
            'sinks':       ('list', 'sinks'),
            'sources':     ('list', 'sources'),
            'sink_inputs': ('list', 'sink-inputs'),
            'src_outputs': ('list', 'source-outputs'),
            'info':        ('info',),
        }
        results = {}
        try:
            with ThreadPoolExecutor(max_workers=5) as ex:
                futures = {ex.submit(pactl_json, *args): key
                           for key, args in queries.items()}
                for fut in as_completed(futures):
                    key = futures[fut]
                    try:
                        results[key] = fut.result() or ([] if key != 'info' else {})
                    except Exception:
                        results[key] = {} if key == 'info' else []
        finally:
            self._loading = False
        server_name = detect_audio_server()
        GLib.idle_add(self._rebuild_ui,
                      results['sinks'], results['sources'],
                      results['sink_inputs'], results['src_outputs'],
                      results['info'], server_name)

    def _rebuild_ui(self, sinks, sources, sink_inputs, src_outputs, info, server_name):
        self._blocks = {}
        for t in (self.tab_out, self.tab_in, self.tab_gen):
            self._clear_tab(t)

        default_sink   = info.get('default_sink_name',   '')
        default_source = info.get('default_source_name', '')

        if not self._cfg.show_monitors:
            sources = [s for s in sources
                       if '.monitor' not in s.get('name', '')]
        real_sources = [s for s in sources
                        if '.monitor' not in s.get('name', '')]

        # ── TAB SALIDAS ───────────────────────────────────────────────
        # populate() es inteligente: si la lista no cambió no toca el combo
        self.sel_sink.populate(sinks, default_sink)

        if sinks:
            self._section_label(self.tab_out, 'Dispositivos de salida',
                                'audio-card', C_SINK)
            for s in sinks:
                idx  = s.get('index', 0)
                name = device_display_name(s)
                vol  = vol_pct(s.get('volume', {}))
                mut  = s.get('mute', False)
                blk  = DeviceBlock('sink', idx, name, vol, mut,
                                   self._on_vol, self._on_mute,
                                   self._interact_start, self._interact_end)
                self._blocks[('sink', idx)] = blk
                self.tab_out['box'].pack_start(blk, False, False, 0)
        else:
            self._section_label(self.tab_out, 'Sin dispositivos de salida',
                                None, C_MUTED)

        if self._cfg.show_apps and sink_inputs:
            self._sep(self.tab_out)
            self._section_label(self.tab_out, 'Aplicaciones reproduciendo audio',
                                'applications-multimedia', C_APP)
            for si in sink_inputs:
                idx   = si.get('index', 0)
                props = si.get('properties') or {}
                name  = app_display_name(props, f'App {idx}')
                vol   = vol_pct(si.get('volume', {}))
                mut   = si.get('mute', False)
                row   = ChannelRow('app', idx, name, vol, mut,
                                   self._on_vol, self._on_mute,
                                   self._interact_start, self._interact_end)
                self._blocks[('app', idx)] = row
                self.tab_out['box'].pack_start(row, False, False, 2)

        # ── TAB ENTRADAS ──────────────────────────────────────────────
        self.sel_source.populate(real_sources, default_source)

        if real_sources:
            self._section_label(self.tab_in, 'Dispositivos de entrada',
                                'audio-card', C_SOURCE)
            for s in real_sources:
                idx  = s.get('index', 0)
                name = device_display_name(s)
                vol  = vol_pct(s.get('volume', {}))
                mut  = s.get('mute', False)
                blk  = DeviceBlock('source', idx, name, vol, mut,
                                   self._on_vol, self._on_mute,
                                   self._interact_start, self._interact_end)
                self._blocks[('source', idx)] = blk
                self.tab_in['box'].pack_start(blk, False, False, 0)
        else:
            self._section_label(self.tab_in,
                                'Sin dispositivos de entrada', None, C_MUTED)

        if self._cfg.show_src_outputs and src_outputs:
            self._sep(self.tab_in)
            self._section_label(self.tab_in, 'Apps capturando audio',
                                'applications-multimedia', C_SOURCE)
            for so in src_outputs:
                idx   = so.get('index', 0)
                props = so.get('properties') or {}
                name  = app_display_name(props, f'App {idx}')
                vol   = vol_pct(so.get('volume', {}))
                mut   = so.get('mute', False)
                row   = ChannelRow('srcout', idx, name, vol, mut,
                                   self._on_vol, self._on_mute,
                                   self._interact_start, self._interact_end)
                self._blocks[('srcout', idx)] = row
                self.tab_in['box'].pack_start(row, False, False, 2)

        # ── TAB GENERAL ───────────────────────────────────────────────
        self._section_label(self.tab_gen, 'Salida principal',
                            'audio-speakers', C_GEN_OUT)
        def_sink = (next((s for s in sinks
                          if s.get('name') == default_sink), None)
                    or (sinks[0] if sinks else None))
        if def_sink:
            idx  = def_sink.get('index', 0)
            name = device_display_name(def_sink)
            vol  = vol_pct(def_sink.get('volume', {}))
            mut  = def_sink.get('mute', False)
            blk  = DeviceBlock('gen-out', idx, name, vol, mut,
                               self._on_vol, self._on_mute,
                               self._interact_start, self._interact_end)
            self._blocks[('gen-sink', idx)] = blk
            self.tab_gen['box'].pack_start(blk, False, False, 0)

        self._sep(self.tab_gen)
        self._section_label(self.tab_gen, 'Entrada principal',
                            'audio-input-microphone', C_GEN_IN)

        def_src = (next((s for s in real_sources
                         if s.get('name') == default_source), None)
                   or (real_sources[0] if real_sources else None))
        if def_src:
            idx  = def_src.get('index', 0)
            name = device_display_name(def_src)
            vol  = vol_pct(def_src.get('volume', {}))
            mut  = def_src.get('mute', False)
            blk  = DeviceBlock('gen-in', idx, name, vol, mut,
                               self._on_vol, self._on_mute,
                               self._interact_start, self._interact_end)
            self._blocks[('gen-source', idx)] = blk
            self.tab_gen['box'].pack_start(blk, False, False, 0)

        if self._cfg.show_apps and sink_inputs:
            self._sep(self.tab_gen)
            self._section_label(self.tab_gen, 'Aplicaciones con audio activo',
                                'applications-multimedia', C_APP)
            for si in sink_inputs:
                idx   = si.get('index', 0)
                props = si.get('properties') or {}
                name  = app_display_name(props, f'App {idx}')
                vol   = vol_pct(si.get('volume', {}))
                mut   = si.get('mute', False)
                row   = ChannelRow('app', idx, name, vol, mut,
                                   self._on_vol, self._on_mute,
                                   self._interact_start, self._interact_end)
                self._blocks[('app-gen', idx)] = row
                self.tab_gen['box'].pack_start(row, False, False, 2)

        interval_s = self._cfg.refresh_interval / 1000
        n_apps = len(sink_inputs)
        apps_str = f'{n_apps} app' + ('' if n_apps == 1 else 's')
        self.status_lbl.set_text(
            f'{server_name}  ·  '
            f'{len(sinks)} salida{'s' if len(sinks) != 1 else ''}  '
            f'{len(real_sources)} entrada{'s' if len(real_sources) != 1 else ''}  '
            f'{apps_str}  '
            f'↺ {interval_s:.0f}s')
        self.status_lbl.set_tooltip_text(
            f'Servidor: {server_name}\n'
            f'Dispositivos de salida (altavoces): {len(sinks)}\n'
            f'Dispositivos de entrada (micrófonos): {len(real_sources)}\n'
            f'Aplicaciones con audio activo: {n_apps}\n'
            f'Actualización automática cada {interval_s:.0f} segundos')

        # Solo mostrar zonas dinámicas recién creadas para evitar parpadeo.
        # show_all() sobre toda la ventana toca también los selectores fijos
        # y es la causa directa del parpadeo al cambiar el volumen.
        for t in (self.tab_out, self.tab_in, self.tab_gen):
            t['box'].show_all()
        if self._first_show:
            self._first_show = False
            self.show_all()

        return False  # no repetir idle_add

    # ── Control de interacción (suprime rebuild durante scroll) ────────

    def _interact_start(self):
        self._user_interacting = True

    def _interact_end(self):
        self._user_interacting = False
        return False  # compatible con GLib.timeout_add

    # ── Callbacks vol / mute ──────────────────────────────────────────

    def _on_vol(self, kind, index, value):
        pct = f'{value}%'
        if kind in ('sink', 'gen-out'):
            pactl_cmd('set-sink-volume',          str(index), pct)
        elif kind in ('source', 'gen-in'):
            pactl_cmd('set-source-volume',        str(index), pct)
        elif kind in ('app', 'app-gen'):
            pactl_cmd('set-sink-input-volume',    str(index), pct)
        elif kind == 'srcout':
            pactl_cmd('set-source-output-volume', str(index), pct)

    def _on_mute(self, kind, index):
        def _do():
            if kind in ('sink', 'gen-out'):
                pactl_cmd('set-sink-mute',            str(index), 'toggle')
            elif kind in ('source', 'gen-in'):
                pactl_cmd('set-source-mute',          str(index), 'toggle')
            elif kind in ('app', 'app-gen'):
                pactl_cmd('set-sink-input-mute',      str(index), 'toggle')
            elif kind == 'srcout':
                pactl_cmd('set-source-output-mute',   str(index), 'toggle')
            # Refresco más corto (80 ms) — pactl es síncrono, el cambio ya aplicó
            GLib.timeout_add(80, self._refresh_one, kind, index)
        threading.Thread(target=_do, daemon=True).start()

    def _refresh_one(self, kind, index):
        def _do():
            try:
                if kind in ('sink', 'gen-out'):
                    items = pactl_json('list', 'sinks') or []
                elif kind in ('source', 'gen-in'):
                    items = pactl_json('list', 'sources') or []
                elif kind in ('app', 'app-gen'):
                    items = pactl_json('list', 'sink-inputs') or []
                else:
                    items = pactl_json('list', 'source-outputs') or []
                for item in items:
                    if item.get('index') == index:
                        muted = item.get('mute', False)
                        vol   = vol_pct(item.get('volume', {}))
                        GLib.idle_add(self._apply_state, kind, index, vol, muted)
                        break
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()
        return False

    def _apply_state(self, kind, index, vol, muted):
        for key in [(kind, index), ('gen-sink', index),
                    ('gen-source', index), ('app-gen', index)]:
            blk = self._blocks.get(key)
            if blk:
                blk.update_state(vol, muted)
        return False

    # ── Diálogos ──────────────────────────────────────────────────────

    def _open_config(self, _w):
        dlg = ConfigDialog(self, self._cfg)
        if dlg.run() == Gtk.ResponseType.OK:
            dlg.apply_to(self._cfg)
            self._schedule_refresh()
            self._load_audio()
        dlg.destroy()

    def _open_about(self, _w):
        dlg = build_about_dialog(self)
        dlg.run()
        dlg.destroy()

    def _open_pavucontrol(self, _w):
        try:
            subprocess.Popen(['pavucontrol'],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            dlg = Gtk.MessageDialog(
                parent=self, flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text='pavucontrol no encontrado')
            dlg.format_secondary_text(
                'Instala con:\n  sudo apt install pavucontrol')
            dlg.run()
            dlg.destroy()

    # ── Arrastre ──────────────────────────────────────────────────────

    def _drag_press(self, _w, e):
        if e.button == 1:
            self._dragging = True
            x, y = self.get_position()
            self._drag_x = e.x_root - x
            self._drag_y = e.y_root - y

    def _drag_release(self, _w, _e):
        self._dragging = False

    def _drag_motion(self, _w, e):
        if self._dragging:
            self.move(int(e.x_root - self._drag_x),
                      int(e.y_root - self._drag_y))


# ═══════════════════════════════════════════════════════════════════════
#  Punto de entrada
# ═══════════════════════════════════════════════════════════════════════

class JerryApp(Gtk.Application):
    def __init__(self):
        GLib.set_prgname('com.cuerdos.jerry-mixer')
        GLib.set_application_name(APP_NAME)
        super().__init__(application_id='com.cuerdos.jerry-mixer')

    def do_activate(self):
        win = JerryMixer(self)
        win.show_all()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        subprocess.run(['pactl', 'info'],
                       capture_output=True, timeout=3, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print('ERROR: pactl no encontrado.\n'
              'Instala con:  sudo apt install pulseaudio-utils\n'
              '          o:  sudo apt install pipewire-pulse')
        sys.exit(1)

    app = JerryApp()
    app.run(sys.argv)


if __name__ == '__main__':
    main()