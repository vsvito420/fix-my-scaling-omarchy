#!/usr/bin/env python3
"""fix-my-scaling: physically align two monitors in Hyprland (side, height, scale).

Opens a fullscreen window on every monitor. One monitor shows markers at the
corners of the shared edge, the other one shows two guide lines you drag until
they are physically level with those corners. From that the vertical offset
and a matching scale are calculated, applied live and, on request, saved to
~/.config/hypr/monitors.lua.
"""

import json
import locale
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("FIX_MY_SCALING_PORT", "8765"))
HERE = Path(__file__).resolve().parent
MONITORS_LUA = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hypr/monitors.lua"
PROFILE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "fix-my-scaling-chromium"
TITLE_PREFIX = "fix-my-scaling"
BROWSERS = ("chromium", "google-chrome-stable", "google-chrome", "brave", "brave-browser", "helium")

# Every API call must carry this token, so no web page can talk to the tool
TOKEN = secrets.token_urlsafe(24)

chromium_procs = []
server = None

# Shared UI state that both windows poll
ui = {
    "main": None,         # monitor whose scale stays fixed
    "side": None,         # monitor whose scale is calculated
    "side_pos": "right",  # side of the second monitor relative to the main one
    "main_scale": None,
    "guide_on": None,     # monitor that shows the guide lines (the physically taller one)
    "top": 0.0,           # guide lines as a fraction of the guide monitor's height
    "bottom": 1.0,
    "upright": [],        # monitors whose "up" edge the user has confirmed
}
lock = threading.Lock()


def system_language():
    """'de' or 'en' from FIX_MY_SCALING_LANG or the system locale."""
    for var in ("FIX_MY_SCALING_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return "de" if value.lower().startswith("de") else "en"
    loc = (locale.getlocale()[0] or "").lower()
    return "de" if loc.startswith("de") else "en"


LANG = system_language()


def msg(en, de):
    return de if LANG == "de" else en


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout


def monitors():
    return {m["name"]: m for m in json.loads(sh("hyprctl", "monitors", "-j"))}


def rotated(m):
    return m["transform"] % 2 == 1


def px_size(m):
    """Pixel size after rotation (width, height)."""
    w, h = m["width"], m["height"]
    return (h, w) if rotated(m) else (w, h)


def mm_height(m):
    return m["physicalWidth"] if rotated(m) else m["physicalHeight"]


def clean_scales(m):
    """Scales Hyprland accepts cleanly for this mode (1/120 steps, whole logical pixels)."""
    g = math.gcd(m["width"] * 120, m["height"] * 120)
    return [k / 120 for k in range(120, 481) if g % k == 0]  # 1 .. 4


def snap(m, scale):
    return min(clean_scales(m), key=lambda s: abs(s - scale))


def config_lines():
    """hl.monitor lines from monitors.lua, so mode and rotation are kept."""
    out = {}
    if MONITORS_LUA.exists():
        for line in MONITORS_LUA.read_text().splitlines():
            m = re.match(r'^hl\.monitor\(\{ output = "([^"]+)"', line)
            if m:
                out[m.group(1)] = line
    return out


def mode_of(name, m):
    line = config_lines().get(name, "")
    mm = re.search(r'mode = "([^"]+)"', line)
    return mm.group(1) if mm else f'{m["width"]}x{m["height"]}@{m["refreshRate"]:.2f}'


def estimate(mons, guide=None):
    """Starting values from the EDID millimetres, vertically centred.

    By default the guide lines go on the physically taller monitor, because
    only there both corners of the other monitor fit on screen.
    """
    main, side = mons[ui["main"]], mons[ui["side"]]
    hm, hs = mm_height(main), mm_height(side)
    if hm <= 0 or hs <= 0:
        hm = hs = 1
    if guide is None:
        guide = ui["main"] if hm >= hs else ui["side"]
    ratio = hs / hm if guide == ui["main"] else hm / hs
    ui["guide_on"] = guide
    ui["top"] = max((1 - ratio) / 2, 0.0)
    ui["bottom"] = min(1 - (1 - ratio) / 2, 1.0)


def compute(mons):
    """Scale and positions of both monitors from the guide lines."""
    main, side = mons[ui["main"]], mons[ui["side"]]
    ms = ui["main_scale"]
    mw_px, mh_px = px_size(main)
    sw_px, sh_px = px_size(side)
    wm, hm = mw_px / ms, mh_px / ms
    t, b = ui["top"], ui["bottom"]
    span = max(b - t, 0.01)

    if ui["guide_on"] == ui["main"]:
        # The side monitor is as tall as the span between the lines on the main monitor
        exact = sh_px / (span * hm)
        scale = snap(side, exact)
        hs = sh_px / scale
        sy = (t + b) / 2 * hm - hs / 2
    else:
        # The main monitor is as tall as the span between the lines on the side monitor
        exact = sh_px * span / hm
        scale = snap(side, exact)
        hs = sh_px / scale
        sy = hm / 2 - (t + b) / 2 * hs

    ws = sw_px / scale
    sx = wm if ui["side_pos"] == "right" else -ws
    ox, oy = min(0.0, sx), min(0.0, sy)
    return {
        "exact": exact,
        "scale": scale,
        # Error caused by snapping to a clean scale, in percent
        "error_pct": (exact - scale) / exact * 100,
        "positions": {
            ui["main"]: (round(-ox), round(-oy)),
            ui["side"]: (round(sx - ox), round(sy - oy)),
        },
        "scales": {ui["main"]: ms, ui["side"]: scale},
    }


def suggestions(mons):
    """Main scales for which the side scale snaps almost exactly."""
    keep = ui["main_scale"]
    out = []
    for ms in clean_scales(mons[ui["main"]]):
        if ms <= 2:
            ui["main_scale"] = ms
            r = compute(mons)
            out.append({"main_scale": ms, "side_scale": r["scale"], "error_pct": r["error_pct"]})
    ui["main_scale"] = keep
    out.sort(key=lambda o: (round(abs(o["error_pct"]), 1), abs(o["main_scale"] - keep)))
    return out[:4]


def scale_expr(scale):
    """Scale as an exact fraction (e.g. 4/3), so Lua has no rounding error.

    With 1.33333 a 1080 px panel is 810.002 px wide and Hyprland reports an overlap.
    """
    k = round(scale * 120)
    g = math.gcd(k, 120)
    num, den = k // g, 120 // g
    return str(num) if den == 1 else f"{num}/{den}"


def monitor_line(name, m, x, y, scale):
    parts = [f'output = "{name}"', f'mode = "{mode_of(name, m)}"',
             f'position = "{int(x)}x{int(y)}"', f"scale = {scale_expr(scale)}"]
    if m["transform"]:
        parts.append(f'transform = {int(m["transform"])}')
    return "hl.monitor({ " + ", ".join(parts) + " })"


def overlaps():
    """Overlapping monitors in the current live layout (logical pixels)."""
    boxes = []
    for n, m in monitors().items():
        w, h = px_size(m)
        boxes.append((n, m["x"], m["y"], m["x"] + w / m["scale"], m["y"] + h / m["scale"]))
    bad = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[1] < b[3] - 0.5 and b[1] < a[3] - 0.5 and a[2] < b[4] - 0.5 and b[2] < a[4] - 0.5:
                bad.append((a[0], b[0]))
    return bad


def apply_live(mons, res):
    # Park the side monitor far away first so no intermediate state overlaps,
    # then set the main monitor and finally move the side monitor into place.
    main, side = ui["main"], ui["side"]
    far = max(m["x"] + max(px_size(m)) for m in mons.values()) + 10000
    for line in (
        monitor_line(side, mons[side], far, 0, mons[side]["scale"]),
        monitor_line(main, mons[main], *res["positions"][main], res["scales"][main]),
        monitor_line(side, mons[side], *res["positions"][side], res["scales"][side]),
    ):
        sh("hyprctl", "eval", line)
    time.sleep(0.3)
    return overlaps()


def save(mons, res):
    MONITORS_LUA.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    lines = []
    if MONITORS_LUA.exists():
        backup = MONITORS_LUA.with_name(f"monitors.lua.bak.{int(time.time())}")
        shutil.copy2(MONITORS_LUA, backup)
        lines = MONITORS_LUA.read_text().splitlines()
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r'^hl\.monitor\(\{ output = "([^"]+)"', line)
        if m and m.group(1) in res["positions"]:
            name = m.group(1)
            lines[i] = monitor_line(name, mons[name], *res["positions"][name], res["scales"][name])
            done.add(name)
    for name in res["positions"]:
        if name not in done:
            lines.append(monitor_line(name, mons[name], *res["positions"][name], res["scales"][name]))
    MONITORS_LUA.write_text("\n".join(lines) + "\n")
    # Reload the saved config cleanly so no live intermediate state is left
    time.sleep(0.5)
    sh("hyprctl", "reload")
    time.sleep(0.8)
    return {
        "backup": str(backup) if backup else None,
        "errors": sh("hyprctl", "configerrors").strip(),
        "overlaps": overlaps(),
    }


def state():
    mons = monitors()
    with lock:
        names = sorted(mons)
        if ui["main"] not in mons:
            # Default: an unrotated monitor is the main monitor
            ui["main"] = next((n for n in names if mons[n]["transform"] == 0), names[0])
        if ui["side"] not in mons or ui["side"] == ui["main"]:
            ui["side"] = next((n for n in names if n != ui["main"]), None)
            ui["main_scale"] = None
        if ui["main_scale"] is None:
            ui["main_scale"] = snap(mons[ui["main"]], mons[ui["main"]]["scale"])
            if ui["side"]:
                s, m = mons[ui["side"]], mons[ui["main"]]
                ui["side_pos"] = "right" if s["x"] >= m["x"] else "left"
                estimate(mons)
        return {
            "ui": dict(ui, upright=[n for n in ui["upright"] if n in mons]),
            "orienting": not all(n in ui["upright"] for n in mons),
            "monitors": {n: {
                "name": n, "description": m["description"], "x": m["x"], "y": m["y"],
                "scale": m["scale"], "transform": m["transform"],
                "clean_scales": clean_scales(m),
            } for n, m in mons.items()},
            "result": compute(mons) if ui["side"] else None,
            "suggestions": suggestions(mons) if ui["side"] else [],
        }


def update_ui(body, mons):
    """Apply a UI change from a window. Everything is validated, since names end up in Lua."""
    if body.get("main") in mons and body["main"] != ui["main"]:
        ui["main"], ui["side"] = body["main"], ui["main"]
        ui["side_pos"] = "left" if ui["side_pos"] == "right" else "right"
        ui["main_scale"] = snap(mons[ui["main"]], mons[ui["main"]]["scale"])
        estimate(mons)
    if body.get("side_pos") in ("left", "right"):
        ui["side_pos"] = body["side_pos"]
    if isinstance(body.get("main_scale"), (int, float)):
        ui["main_scale"] = snap(mons[ui["main"]], float(body["main_scale"]))
    for k in ("top", "bottom"):
        if isinstance(body.get(k), (int, float)) and math.isfinite(body[k]):
            ui[k] = float(body[k])
    if body.get("guide_on") in (ui["main"], ui["side"]):
        estimate(mons, body["guide_on"])
    if body.get("estimate"):
        estimate(mons, ui["guide_on"])
    ui["top"] = min(max(ui["top"], 0.0), 0.99)
    ui["bottom"] = min(max(ui["bottom"], ui["top"] + 0.01), 1.0)


# Clockwise order of the screen edges as currently displayed
EDGES = ("top", "right", "bottom", "left")


def set_up(mons, name, edge):
    """The user tapped the edge that is physically up; rotate so it becomes the top.

    Hyprland/Wayland transforms rotate counter-clockwise in 90° steps: if the
    displayed right edge points up, the panel is turned 90° CCW, so add 1.
    """
    if name not in mons or edge not in EDGES:
        return
    if edge == "top":
        if name not in ui["upright"]:
            ui["upright"].append(name)
        return
    m = mons[name]
    t = m["transform"]
    new = (t & 4) | ((t + EDGES.index(edge)) % 4)
    m = dict(m, transform=new)
    sh("hyprctl", "eval", monitor_line(name, m, m["x"], m["y"], m["scale"]))
    time.sleep(0.5)
    # Sizes changed, so start the alignment from scratch
    ui["main"] = ui["side"] = ui["main_scale"] = None


def close_windows():
    for p in chromium_procs:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, query):
        token = self.headers.get("X-Token") or query.get("token", [""])[0]
        return secrets.compare_digest(token, TOKEN)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self.authorized(query):
            self.send(403, "{}")
            return
        if url.path == "/":
            mon = re.sub(r"[^A-Za-z0-9._-]", "", query.get("mon", [""])[0])
            html = (HERE / "index.html").read_text()
            html = (html.replace("__TITLE__", f"{TITLE_PREFIX} {mon}")
                        .replace("__LANG__", LANG)
                        .replace("__TOKEN__", TOKEN))
            self.send(200, html, "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self.send(200, json.dumps(state()))
        else:
            self.send(404, "{}")

    def do_POST(self):
        url = urlparse(self.path)
        if not self.authorized({}) or self.headers.get("Content-Type") != "application/json":
            self.send(403, "{}")
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        mons = monitors()
        reply = {}
        with lock:
            if url.path == "/api/up":
                set_up(mons, body.get("mon"), body.get("edge"))
            elif url.path == "/api/reorient":
                ui["upright"] = []
            elif url.path == "/api/ui":
                update_ui(body, mons)
            elif url.path == "/api/apply":
                reply = {"overlaps": apply_live(mons, compute(mons))}
            elif url.path == "/api/save":
                reply = save(mons, compute(mons))
            elif url.path == "/api/revert":
                sh("hyprctl", "reload")
            elif url.path == "/api/quit":
                self.send(200, "{}")
                threading.Thread(target=shutdown, daemon=True).start()
                return
            else:
                self.send(404, "{}")
                return
        self.send(200, json.dumps(reply))


def dispatch(lua):
    sh("hyprctl", "dispatch", lua)


def find_browser():
    for b in BROWSERS:
        path = shutil.which(b)
        if path:
            return path
    return None


def open_windows():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    for name in sorted(monitors()):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            continue
        dispatch(f'hl.dsp.focus({{ monitor = "{name}" }})')
        p = subprocess.Popen(
            [browser, f"--user-data-dir={PROFILE_DIR}", "--no-first-run", "--no-default-browser-check",
             f"--app=http://127.0.0.1:{PORT}/?mon={name}&token={TOKEN}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        chromium_procs.append(p)
        title = f"{TITLE_PREFIX} {name}"
        for _ in range(50):
            if title in sh("hyprctl", "clients"):
                break
            time.sleep(0.2)
        dispatch(f'hl.dsp.focus({{ window = "title:^{title}$" }})')
        dispatch(f'hl.dsp.window.move({{ monitor = "{name}" }})')
        dispatch('hl.dsp.window.fullscreen({ mode = "fullscreen" })')


def shutdown():
    time.sleep(0.2)
    close_windows()
    server.shutdown()


def stop_running_instance():
    """Ask an already running instance to quit (it answers /api/quit only with its token)."""
    pid_file = PROFILE_DIR / "server.pid"
    try:
        os.kill(int(pid_file.read_text()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    time.sleep(1.5)


def main():
    global server
    if not shutil.which("hyprctl"):
        sys.exit(msg("Hyprland (hyprctl) not found.", "Hyprland (hyprctl) nicht gefunden."))
    if not find_browser():
        sys.exit(msg("No Chromium-based browser found.", "Kein Chromium-basierter Browser gefunden."))
    if len(monitors()) < 2:
        sys.exit(msg("Only one monitor connected.", "Nur ein Monitor angeschlossen."))
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError:
            if attempt:
                sys.exit(msg(f"Port {PORT} is in use.", f"Port {PORT} ist belegt."))
            # Already running: stop the old instance and start fresh
            stop_running_instance()
    (PROFILE_DIR / "server.pid").write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *a: threading.Thread(target=shutdown).start())
    threading.Thread(target=open_windows, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        close_windows()


if __name__ == "__main__":
    main()
