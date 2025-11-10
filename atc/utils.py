import math, os, sys, pygame
from constants import *

def ensure_pygame_ready():
    """Safely initialize Pygame and its font subsystem if not active."""
    if not pygame.get_init():
        pygame.init()
    if not pygame.font.get_init():
        pygame.font.init()

def get_current_version() -> str:
    """Return app version from version.txt (works both frozen and unfrozen)."""
    try:
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(sys.argv[0]))

        version_path = os.path.join(base_path, "version.txt")

        if not os.path.exists(version_path):
            version_path = os.path.join(os.path.dirname(base_path), "version.txt")

        with open(version_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "v0.0.0"

def load_runways(): return RUNWAYS
def nm_to_px(nm): return nm/NM_PER_PX
def px_to_nm(px): return px*NM_PER_PX
def heading_to_vec(hdg): return math.sin(math.radians(hdg)), -math.cos(math.radians(hdg))
def normalize_hdg(h): return h % 360
def shortest_turn_dir(a, b): return 1 if (b - a + 360) % 360 <= 180 else -1

def get_callsign_from_iata(callsign: str) -> str:
    from constants import AIRLINES

    prefix = callsign[:2].upper()
    number = callsign[2:].lstrip("0")

    for airline, data in AIRLINES.items():
        if prefix == data["IATA"].upper():
            return f"{data['Callsign']} {number}"

    return callsign

def get_heading_to_fix(ac, fix):
    dx = fix["x"] - ac.x
    dy = fix["y"] - ac.y
    angle = math.degrees(math.atan2(dx, -dy)) 
    return normalize_hdg(angle)

def distance_to_fix(ac, fix):
    dx = fix["x"] - ac.x
    dy = fix["y"] - ac.y
    return px_to_nm(math.hypot(dx, dy))

def check_conflicts(planes):
    res = []
    for i, a in enumerate(planes):
        for b in planes[i + 1:]:
            if a.state == "LANDED" or b.state == "LANDED": continue
            lat = a.distance_nm(b)
            vert = a.vert_sep(b)
            if lat < SAFE_LAT_NM and vert < SAFE_VERT_FT:
                res.append((a, b, lat, vert))
    return res

def load_fixes(layout: dict | None = None):
    """Return dynamically scaled fix coordinates based on current layout."""
    if layout is None:
        layout = calculate_layout(WIDTH, HEIGHT)

    radar_width = layout["RADAR_WIDTH"]
    radar_height = layout["RADAR_HEIGHT"]

    scale_x = radar_width / WIDTH
    scale_y = radar_height / HEIGHT

    scaled = {}
    for name, pos in FIXES.items():
        scaled[name] = {
            "x": int(pos["x"] * scale_x),
            "y": int(pos["y"] * scale_y),
        }
    return scaled

def calculate_layout(width: int, height: int) -> dict:
    """Generate a responsive, scale-aware layout for PyATC."""

    sidebar_ratio = 0.18
    console_ratio = 0.07
    font_ratio_base = 0.022
    ring_scale_base = 1500

    sidebar_width = int(width * sidebar_ratio)
    console_height = max(40, int(height * console_ratio))

    # === Multi-font scaling with independent caps ===
    font_size_radar = max(12, int(height * font_ratio_base * 1.0))
    font_size_sidebar = max(12, int(height * font_ratio_base * 0.9))
    font_size_console = max(12, int(height * font_ratio_base * 1.1))

    MAX_RADAR_FONT = 26
    MAX_SIDEBAR_FONT = 24
    MAX_CONSOLE_FONT = 28

    font_size_radar = min(font_size_radar, MAX_RADAR_FONT)
    font_size_sidebar = min(font_size_sidebar, MAX_SIDEBAR_FONT)
    font_size_console = min(font_size_console, MAX_CONSOLE_FONT)

    sidebar_rect = pygame.Rect(width - sidebar_width, 0, sidebar_width, height - console_height)
    radar_rect = pygame.Rect(0, 0, width - sidebar_width, height - console_height)
    console_rect = pygame.Rect(0, height - console_height, width, console_height)

    ring_scale = radar_rect.width / ring_scale_base

    layout = {
        "SIDEBAR_RECT": sidebar_rect,
        "RADAR_RECT": radar_rect,
        "CONSOLE_RECT": console_rect,
        "RADAR_CENTER": radar_rect.center,
        "SIDEBAR_WIDTH": sidebar_width,
        "RADAR_WIDTH": radar_rect.width,
        "RADAR_HEIGHT": radar_rect.height,
        "BOTTOM_MARGIN": console_height,
        "RING_SCALE": ring_scale,

        "FONT_SIZE_RADAR": font_size_radar,
        "FONT_SIZE_SIDEBAR": font_size_sidebar,
        "FONT_SIZE_CONSOLE": font_size_console,

        "FONT_SIZE": font_size_radar,
    }

    return layout

def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = f"{current} {word}".strip()
        if font.size(test)[0] <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def convert_to_phraseology(value: int, type: str) -> str:
    numwords = {
        "0": "zero", "1": "one", "2": "two", "3": "three",
        "4": "four", "5": "five", "6": "six", "7": "seven",
        "8": "eight", "9": "nine"
    }

    if type.lower() == "altitude":
        altitude = int(value)
        if altitude >= 18000:
            fl = int(round(altitude / 100))
            digits = [numwords[d] for d in str(fl)]
            return f"flight level {' '.join(digits)}"
        else:
            thousands = altitude // 1000
            digits = [numwords[d] for d in str(thousands)]
            return f"{' '.join(digits)} thousand"

    elif type.lower() == "heading":
        h_str = f"{int(value):03d}"
        return " ".join(numwords[d] for d in h_str)

    elif type.lower() == "speed":
        s_str = str(int(value))
        return " ".join(numwords[d] for d in s_str) + " knots"

    return str(value)

def scale_position(x, y, layout: dict) -> tuple[int, int]:
    """Scale radar/world coordinates according to current layout."""
    scale_x = layout["RADAR_WIDTH"] / WIDTH
    scale_y = layout["RADAR_HEIGHT"] / HEIGHT
    return int(x * scale_x), int(y * scale_y)