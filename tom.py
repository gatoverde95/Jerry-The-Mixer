#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
#  TOM — Volume Applet  │  PulseAudio-powered  │  X11 & Wayland
#  Companion to Jerry The Mixer (jerry-mixer)
# ─────────────────────────────────────────────────────────────────────────────

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import subprocess
import sys
import os
import signal
import threading
import json
import re

# Try AppIndicator3
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3
    HAS_INDICATOR = True
except (ImportError, ValueError):
    HAS_INDICATOR = False

# ─────────────────────────────────────────────────────────────────────────────
#  PulseAudio Backend (pactl / pulseaudio-utils)
# ─────────────────────────────────────────────────────────────────────────────

def pactl(*args, capture=True):
    try:
        r = subprocess.run(["pactl"] + list(args),
                           capture_output=capture, text=True, timeout=3)
        return r.stdout.strip() if capture else (r.returncode == 0)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

def get_default_sink():
    return pactl("get-default-sink") or ""

def get_volume():
    sink = get_default_sink()
    if not sink:
        return 50
    out = pactl("get-sink-volume", sink) or ""
    m = re.search(r"(\d+)%", out)
    return int(m.group(1)) if m else 50

def get_mute():
    sink = get_default_sink()
    if not sink:
        return False
    out = pactl("get-sink-mute", sink) or ""
    return "yes" in out.lower()

def set_volume(v):
    v = max(0, min(150, int(v)))
    sink = get_default_sink()
    if sink:
        pactl("set-sink-volume", sink, f"{v}%", capture=False)

def toggle_mute():
    sink = get_default_sink()
    if sink:
        pactl("set-sink-mute", sink, "toggle", capture=False)

def get_sinks():
    out = pactl("--format=json", "list", "sinks") or "[]"
    try:
        return [(s.get("name",""), s.get("description", s.get("name","")))
                for s in json.loads(out)]
    except Exception:
        return []

def set_default_sink(name):
    pactl("set-default-sink", name, capture=False)

def get_mic_volume():
    out = pactl("get-source-volume", "@DEFAULT_SOURCE@") or ""
    m = re.search(r"(\d+)%", out)
    return int(m.group(1)) if m else 50

def get_mic_mute():
    out = pactl("get-source-mute", "@DEFAULT_SOURCE@") or ""
    return "yes" in out.lower()

def toggle_mic_mute():
    pactl("set-source-mute", "@DEFAULT_SOURCE@", "toggle", capture=False)

def set_mic_volume(v):
    v = max(0, min(150, int(v)))
    pactl("set-source-volume", "@DEFAULT_SOURCE@", f"{v}%", capture=False)

# ─────────────────────────────────────────────────────────────────────────────
#  CSS — "Phosphor" theme: deep obsidian + warm amber glow
# ─────────────────────────────────────────────────────────────────────────────

CSS = b"""
* { font-family: "Space Mono", "Courier New", monospace; }

#tom-main {
    background: #0c0c0a;
    border: 1px solid #2e2e22;
    border-radius: 14px;
    box-shadow: 0 12px 48px rgba(0,0,0,0.9), inset 0 1px 0 #2a2a1e;
}

#tom-header {
    background: #101010;
    border-bottom: 1px solid #1e1e16;
    border-radius: 14px 14px 0 0;
    padding: 10px 16px 9px;
}

#tom-title {
    color: #c8a84b;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.2em;
}

#tom-sub {
    color: #3e3e2e;
    font-size: 8px;
    letter-spacing: 0.18em;
    margin-top: 1px;
}

#tom-body { padding: 14px 16px 16px; }

.sec-lbl {
    color: #464636;
    font-size: 8px;
    letter-spacing: 0.2em;
    margin-bottom: 2px;
}

#vol-num {
    color: #c8a84b;
    font-size: 34px;
    font-weight: 700;
}
#vol-num.muted { color: #2a2a20; }
#vol-pct { color: #504e38; font-size: 12px; }

scale trough {
    background: #181810;
    border-radius: 4px;
    min-height: 5px;
    border: 1px solid #242418;
}
scale highlight, scale fill {
    background: linear-gradient(to right, #7a5c10, #c8a84b);
    border-radius: 4px;
}
scale slider {
    background: #c8a84b;
    border-radius: 50%;
    min-width: 14px;
    min-height: 14px;
    box-shadow: 0 0 8px rgba(200,168,75,0.5);
    border: none;
    transition: all 60ms;
}
scale slider:hover { background: #e0c060; }

#mic-sc trough  { background: #10101a; border-color: #1e1e2a; }
#mic-sc highlight, #mic-sc fill {
    background: linear-gradient(to right, #12305a, #3a78c8);
}
#mic-sc slider { background: #3a78c8; box-shadow: 0 0 8px rgba(58,120,200,0.5); }
#mic-sc slider:hover { background: #5090e0; }

button {
    background: #141410;
    border: 1px solid #282820;
    border-radius: 6px;
    color: #6a6a50;
    padding: 5px 10px;
    font-family: "Space Mono", monospace;
    font-size: 9px;
    letter-spacing: 0.06em;
    transition: all 60ms;
}
button:hover { background: #1e1e18; border-color: #3e3e2e; color: #9a9878; }
button:active { background: #0a0a08; }

button.mute-btn {
    min-width: 90px;
    background: #161410;
    border-color: #302c1a;
    color: #b09038;
}
button.mute-btn:hover { border-color: #c8a84b; color: #e0c060; }
button.mute-btn.is-muted { background: #0c0c0c; border-color: #202018; color: #362e18; }

button.jerry-btn {
    background: #0e1218;
    border-color: #1e2838;
    color: #3a78c8;
    font-size: 9px;
}
button.jerry-btn:hover { border-color: #3a78c8; color: #70a8f8; }

button.quick-btn {
    min-width: 36px;
    padding: 4px 6px;
    font-size: 9px;
}

combobox button {
    background: #111110;
    border-color: #202018;
    color: #5a5a42;
    font-size: 9px;
}

separator { background: #181812; min-height: 1px; margin: 6px 0; }
"""

# ─────────────────────────────────────────────────────────────────────────────
#  Popup Window
# ─────────────────────────────────────────────────────────────────────────────

class TomPopup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self._busy = False
        self._loading = True

        self.set_name("tom-window")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)

        # Apply CSS
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # RGBA visual for transparency
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.set_app_paintable(True)

        self._build_ui()
        self._loading = False

        self.connect("focus-out-event", lambda *_: GLib.timeout_add(180, self._maybe_hide))
        self.connect("key-press-event", self._on_key)
        GLib.timeout_add(1800, self._refresh_loop)

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.set_name("tom-main")

        # Header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        hdr.set_name("tom-header")
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lbl = Gtk.Label(label="TOM"); lbl.set_name("tom-title"); lbl.set_halign(Gtk.Align.START)
        sub = Gtk.Label(label="VOLUME APPLET"); sub.set_name("tom-sub"); sub.set_halign(Gtk.Align.START)
        tbox.pack_start(lbl, False, False, 0)
        tbox.pack_start(sub, False, False, 0)
        close = Gtk.Button(label="✕")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.connect("clicked", lambda _: self.hide())
        hdr.pack_start(tbox, True, True, 0)
        hdr.pack_end(close, False, False, 0)

        # Body
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.set_name("tom-body")

        # ── Output ─────────────
        out_lbl = Gtk.Label(label="OUTPUT")
        out_lbl.get_style_context().add_class("sec-lbl")
        out_lbl.set_halign(Gtk.Align.START)

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.vol_lbl = Gtk.Label(label="50"); self.vol_lbl.set_name("vol-num")
        self.vol_lbl.set_width_chars(3); self.vol_lbl.set_xalign(1.0)
        pct = Gtk.Label(label="%"); pct.set_name("vol-pct"); pct.set_valign(Gtk.Align.END)
        self.mute_btn = Gtk.Button(label="🔊 LIVE")
        self.mute_btn.get_style_context().add_class("mute-btn")
        self.mute_btn.connect("clicked", self._on_mute)
        row1.pack_start(self.vol_lbl, False, False, 0)
        row1.pack_start(pct, False, False, 0)
        row1.pack_end(self.mute_btn, False, False, 0)

        self.vol_adj = Gtk.Adjustment(value=50, lower=0, upper=150,
                                      step_increment=1, page_increment=5)
        self.vol_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL,
                                   adjustment=self.vol_adj)
        self.vol_scale.set_draw_value(False); self.vol_scale.set_hexpand(True)
        for v in (0, 50, 100, 150):
            self.vol_scale.add_mark(v, Gtk.PositionType.BOTTOM,
                                    "│" if v in (0, 150) else "▾")
        self.vol_scale.connect("value-changed", self._on_vol_change)

        # ── Input ──────────────
        sep1 = Gtk.Separator()
        in_lbl = Gtk.Label(label="INPUT")
        in_lbl.get_style_context().add_class("sec-lbl")
        in_lbl.set_halign(Gtk.Align.START)

        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.mic_lbl = Gtk.Label(label="50")
        self.mic_lbl.set_width_chars(3); self.mic_lbl.set_xalign(1.0)
        mpct = Gtk.Label(label="%"); mpct.set_valign(Gtk.Align.END)
        self.mic_mute_btn = Gtk.Button(label="🎙 LIVE")
        self.mic_mute_btn.get_style_context().add_class("mute-btn")
        self.mic_mute_btn.connect("clicked", self._on_mic_mute)
        row2.pack_start(self.mic_lbl, False, False, 0)
        row2.pack_start(mpct, False, False, 0)
        row2.pack_end(self.mic_mute_btn, False, False, 0)

        self.mic_adj = Gtk.Adjustment(value=50, lower=0, upper=150,
                                      step_increment=1, page_increment=5)
        self.mic_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL,
                                   adjustment=self.mic_adj)
        self.mic_scale.set_name("mic-sc")
        self.mic_scale.set_draw_value(False); self.mic_scale.set_hexpand(True)
        for v in (0, 100, 150):
            self.mic_scale.add_mark(v, Gtk.PositionType.BOTTOM, "▾")
        self.mic_scale.connect("value-changed", self._on_mic_change)

        # ── Device selector ────
        sep2 = Gtk.Separator()
        dev_lbl = Gtk.Label(label="DEVICE")
        dev_lbl.get_style_context().add_class("sec-lbl")
        dev_lbl.set_halign(Gtk.Align.START)
        self.sink_combo = Gtk.ComboBoxText()
        self._sink_names = []
        self.sink_combo.connect("changed", self._on_sink_change)
        self._populate_sinks()

        # ── Actions ────────────
        sep3 = Gtk.Separator()
        act = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)

        qbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        for lbl_t, v in [("0", 0), ("25", 25), ("50", 50), ("75", 75), ("100", 100)]:
            b = Gtk.Button(label=lbl_t)
            b.get_style_context().add_class("quick-btn")
            b.connect("clicked", lambda _, val=v: self._quick_vol(val))
            qbox.pack_start(b, False, False, 0)

        jerry = Gtk.Button(label="⚙ JERRY MIXER")
        jerry.get_style_context().add_class("jerry-btn")
        jerry.connect("clicked", self._launch_jerry)

        act.pack_start(qbox, False, False, 0)
        act.pack_end(jerry, False, False, 0)

        # Pack
        for w in [out_lbl, row1, self.vol_scale,
                  sep1, in_lbl, row2, self.mic_scale,
                  sep2, dev_lbl, self.sink_combo,
                  sep3, act]:
            body.pack_start(w, False, False, 0)

        root.pack_start(hdr, False, False, 0)
        root.pack_start(body, True, True, 0)
        self.add(root)
        root.show_all()
        self.set_default_size(330, -1)

    # ── State helpers ────────────────────────────────────────────────────────

    def _populate_sinks(self):
        self.sink_combo.remove_all()
        self._sink_names.clear()
        default = get_default_sink()
        sinks = get_sinks()
        active = 0
        for i, (name, desc) in enumerate(sinks):
            short = (desc[:44] + "…") if len(desc) > 44 else desc
            self.sink_combo.append_text(short)
            self._sink_names.append(name)
            if name == default:
                active = i
        self.sink_combo.set_active(active)

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        try:
            vol   = get_volume()
            muted = get_mute()
            mvol  = get_mic_volume()
            mmute = get_mic_mute()

            self.vol_adj.set_value(vol)
            self.vol_lbl.set_text(str(vol))
            ctx = self.vol_lbl.get_style_context()
            if muted:
                ctx.add_class("muted")
                self.mute_btn.set_label("🔇 MUTED")
                self.mute_btn.get_style_context().add_class("is-muted")
            else:
                ctx.remove_class("muted")
                ico = "🔊" if vol >= 50 else ("🔉" if vol > 0 else "🔈")
                self.mute_btn.set_label(f"{ico} LIVE")
                self.mute_btn.get_style_context().remove_class("is-muted")

            self.mic_adj.set_value(mvol)
            self.mic_lbl.set_text(str(mvol))
            if mmute:
                self.mic_mute_btn.set_label("🚫 MUTED")
                self.mic_mute_btn.get_style_context().add_class("is-muted")
            else:
                self.mic_mute_btn.set_label("🎙 LIVE")
                self.mic_mute_btn.get_style_context().remove_class("is-muted")
        finally:
            self._busy = False

    def _refresh_loop(self):
        if self.get_visible():
            self.refresh()
        return True

    def show_near_cursor(self):
        self.refresh()
        self._populate_sinks()
        disp = Gdk.Display.get_default()
        x, y = 100, 100
        if disp:
            try:
                seat = disp.get_default_seat()
                _, x, y = seat.get_pointer().get_position()
            except Exception:
                pass
        scr  = Gdk.Screen.get_default()
        sw, sh = scr.get_width(), scr.get_height()
        pw, ph = 330, 400
        px = max(10, min(x, sw - pw - 10))
        py = max(10, min(y - 20, sh - ph - 44))
        self.move(px, py)
        self.show_all()
        self.present()
        self.grab_focus()

    def toggle(self):
        if self.get_visible():
            self.hide()
        else:
            self.show_near_cursor()

    # ── Events ───────────────────────────────────────────────────────────────

    def _maybe_hide(self):
        if not self.has_toplevel_focus():
            self.hide()

    def _on_key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.hide()

    def _on_vol_change(self, sc):
        if self._loading or self._busy:
            return
        v = int(sc.get_value())
        self.vol_lbl.set_text(str(v))
        set_volume(v)

    def _on_mute(self, *_):
        toggle_mute()
        GLib.timeout_add(120, self.refresh)

    def _on_mic_change(self, sc):
        if self._loading or self._busy:
            return
        v = int(sc.get_value())
        self.mic_lbl.set_text(str(v))
        set_mic_volume(v)

    def _on_mic_mute(self, *_):
        toggle_mic_mute()
        GLib.timeout_add(120, self.refresh)

    def _on_sink_change(self, combo):
        if self._loading:
            return
        idx = combo.get_active()
        if 0 <= idx < len(self._sink_names):
            set_default_sink(self._sink_names[idx])
            GLib.timeout_add(250, self.refresh)

    def _quick_vol(self, v):
        set_volume(v)
        GLib.timeout_add(120, self.refresh)

    def _launch_jerry(self, *_):
        try:
            subprocess.Popen(["jerry-mixer"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            dlg = Gtk.MessageDialog(
                transient_for=self, flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="jerry-mixer not found")
            dlg.format_secondary_text(
                "Install jerry-mixer to use the full mixer.\n"
                "Example: sudo apt install jerry-mixer")
            dlg.run(); dlg.destroy()

# ─────────────────────────────────────────────────────────────────────────────
#  Tray / Indicator
# ─────────────────────────────────────────────────────────────────────────────

class TomTray:
    def __init__(self):
        self.popup = TomPopup()

        if HAS_INDICATOR:
            self._build_indicator()
        else:
            self._build_status_icon()

        signal.signal(signal.SIGTERM, self._quit)
        signal.signal(signal.SIGINT,  self._quit)
        self._pulse_monitor()

    # ── Indicator (AppIndicator3) ─────────────────────────────────────────

    def _build_indicator(self):
        self.ind = AppIndicator3.Indicator.new(
            "tom-applet", "audio-volume-high",
            AppIndicator3.IndicatorCategory.HARDWARE)
        self.ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.ind.set_title("Tom — Volume")
        self.ind.set_menu(self._make_menu())

    def _make_menu(self):
        m = Gtk.Menu()

        open_i = Gtk.MenuItem(label="🎚  Open Tom…")
        open_i.connect("activate", lambda _: self.popup.show_near_cursor())
        m.append(open_i)

        jerry_i = Gtk.MenuItem(label="⚙  Jerry Mixer")
        jerry_i.connect("activate", lambda _: self.popup._launch_jerry())
        m.append(jerry_i)

        m.append(Gtk.SeparatorMenuItem())

        mute_i = Gtk.MenuItem(label="🔇  Toggle Mute")
        mute_i.connect("activate", lambda _: (toggle_mute(), self._update_icon()))
        m.append(mute_i)

        m.append(Gtk.SeparatorMenuItem())

        q_i = Gtk.MenuItem(label="Quit Tom")
        q_i.connect("activate", self._quit)
        m.append(q_i)

        m.show_all()
        return m

    # ── StatusIcon fallback (X11) ─────────────────────────────────────────

    def _build_status_icon(self):
        self.si = Gtk.StatusIcon()
        self.si.set_from_icon_name("audio-volume-high")
        self.si.set_tooltip_text("Tom — Volume Applet")
        self.si.connect("activate", lambda _: self.popup.toggle())
        self.si.connect("popup-menu", self._si_menu)
        self.si.connect("scroll-event", self._on_scroll)

    def _si_menu(self, icon, btn, t):
        m = Gtk.Menu()
        j = Gtk.MenuItem(label="⚙ Jerry Mixer")
        j.connect("activate", lambda _: self.popup._launch_jerry())
        m.append(j)
        m.append(Gtk.SeparatorMenuItem())
        q = Gtk.MenuItem(label="Quit")
        q.connect("activate", self._quit)
        m.append(q)
        m.show_all()
        m.popup(None, None, None, None, btn, t)

    def _on_scroll(self, w, steps, direction, *_):
        delta = 5 if direction == Gdk.ScrollDirection.UP else -5
        set_volume(get_volume() + delta)
        self._update_icon()

    # ── Shared ────────────────────────────────────────────────────────────

    def _update_icon(self):
        vol   = get_volume()
        muted = get_mute()
        if muted or vol == 0:
            icon = "audio-volume-muted"
        elif vol < 34:
            icon = "audio-volume-low"
        elif vol < 67:
            icon = "audio-volume-medium"
        else:
            icon = "audio-volume-high"
        tip = f"Tom — {'MUTED' if muted else f'{vol}%'}"
        if HAS_INDICATOR:
            self.ind.set_icon_full(icon, tip)
        else:
            self.si.set_from_icon_name(icon)
            self.si.set_tooltip_text(tip)

    def _pulse_monitor(self):
        """Watch pactl subscribe for sink events → update icon."""
        def _run():
            try:
                proc = subprocess.Popen(["pactl", "subscribe"],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)
                for line in proc.stdout:
                    if "sink" in line or "server" in line:
                        GLib.idle_add(self._update_icon)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _quit(self, *_):
        Gtk.main_quit()

    def run(self):
        self._update_icon()
        Gtk.main()

# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Dependency check
    try:
        subprocess.run(["pactl", "--version"], capture_output=True, timeout=2, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("Tom: 'pactl' not found. Install pulseaudio-utils:", file=sys.stderr)
        print("  sudo apt install pulseaudio-utils", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("Tom: pactl timed out — is PulseAudio/PipeWire running?", file=sys.stderr)
        sys.exit(1)

    TomTray().run()

