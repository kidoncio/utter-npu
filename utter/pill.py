#!/usr/bin/python3
"""Utter pill: status indicator at the top of the screen (GTK4 + wlr-layer-shell).

Reads utter.protocol messages from stdin, one per line. Never takes keyboard
focus and lets clicks pass through. Runs on the system Python and needs
LD_PRELOAD=libgtk4-layer-shell.so (a gtk4-layer-shell requirement).
"""
import os
import sys
from collections import deque
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
import cairo  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utter.i18n import strings_for  # noqa: E402
from utter.protocol import Done, Failed, Hide, Recording, Waiting, decode  # noqa: E402

T = strings_for(os.environ)

CSS = b"""
window { background: transparent; }
.pill {
  border-radius: 999px; padding: 7px 16px; color: white;
  font-weight: 600; font-size: 15px;
  box-shadow: 0 3px 10px rgba(0,0,0,.45);
}
.rec  { background: #d93636; }
.wait { background: #c98a10; }
.done { background: #1f9d55; }
.fail { background: #555b63; }
.timer { font-feature-settings: "tnum"; opacity: .9; }
"""

N_BARS = 7


class Pill(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.kidoncio.UtterPill")
        self.levels = deque([0.0] * N_BARS, maxlen=N_BARS)

    def do_activate(self):
        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gtk.Widget.get_display(Gtk.Label()), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        w = self.win = Gtk.Window(application=self)
        Layer.init_for_window(w)
        Layer.set_layer(w, Layer.Layer.OVERLAY)
        Layer.set_anchor(w, Layer.Edge.TOP, True)
        Layer.set_margin(w, Layer.Edge.TOP, 14)
        Layer.set_keyboard_mode(w, Layer.KeyboardMode.NONE)
        Layer.set_namespace(w, "utter")

        self.box = Gtk.Box(spacing=8)
        self.box.add_css_class("pill")
        self.icon = Gtk.Label()
        self.spinner = Gtk.Spinner()
        self.text = Gtk.Label()
        self.bars = Gtk.DrawingArea(content_width=N_BARS * 4, content_height=16)
        self.bars.set_draw_func(self._draw_bars)
        self.timer = Gtk.Label()
        self.timer.add_css_class("timer")
        for child in (self.icon, self.spinner, self.text, self.bars, self.timer):
            self.box.append(child)
        w.set_child(self.box)
        # Clicks pass through the pill: empty input region.
        w.connect("realize", lambda *_: w.get_surface().set_input_region(cairo.Region()))

        self.hold()  # stay alive while the window is hidden
        ch = GLib.IOChannel.unix_new(sys.stdin.fileno())
        GLib.io_add_watch(ch, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP,
                          self._on_stdin)

    def _on_stdin(self, ch, cond):
        line = sys.stdin.readline()
        if not line:  # daemon closed the pipe
            self.quit()
            return False
        msg = decode(line)
        if msg is not None:
            self.show(msg)
        return True

    def _style(self, css_class, icon, text, recording=False, spinning=False):
        for c in ("rec", "wait", "done", "fail"):
            self.box.remove_css_class(c)
        self.box.add_css_class(css_class)
        self.icon.set_visible(not spinning)
        self.icon.set_text(icon)
        self.spinner.set_visible(spinning)
        self.spinner.set_spinning(spinning)
        self.text.set_text(text)
        self.bars.set_visible(recording)
        self.timer.set_visible(recording)

    def show(self, msg):
        match msg:
            case Recording(level, elapsed):
                if not self.win.get_visible() or not self.box.has_css_class("rec"):
                    self.levels.extend([0.0] * N_BARS)
                    self._style("rec", "●", T["speak"], recording=True)
                self.levels.append(level)
                self.bars.queue_draw()
                m, s = divmod(int(elapsed), 60)
                self.timer.set_text(f"{m}:{s:02d}")
            case Waiting():
                self._style("wait", "", T["transcribing"], spinning=True)
            case Done():
                self._style("done", "✓", T["copied"])
            case Failed(message):
                self._style("fail", "!", message)
            case Hide():
                self.win.set_visible(False)
                return
        self.win.set_visible(True)

    def _draw_bars(self, area, cr, width, height):
        cr.set_source_rgb(1, 1, 1)
        for i, lv in enumerate(self.levels):
            h = max(2.0, lv * height)
            cr.rectangle(i * 4, (height - h) / 2, 2.5, h)
        cr.fill()


if __name__ == "__main__":
    sys.exit(Pill().run([]))
