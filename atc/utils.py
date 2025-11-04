import math
from constants import *

def load_runways(): return RUNWAYS
def nm_to_px(nm): return nm/NM_PER_PX
def px_to_nm(px): return px*NM_PER_PX
def heading_to_vec(hdg): return math.sin(math.radians(hdg)), -math.cos(math.radians(hdg))
def normalize_hdg(h): return h % 360
def shortest_turn_dir(a, b): return 1 if (b - a + 360) % 360 <= 180 else -1

def get_callsign_from_iata(callsign: str) -> str:
    from constants import AIRLINES

    # First two characters are always the IATA prefix
    prefix = callsign[:2].upper()
    number = callsign[2:].lstrip("0")  # remove leading zeros for realism

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

def load_fixes():
    """Return scaled fix coordinates relative to current calculated layout."""
    layout = calculate_layout(WIDTH, HEIGHT)
    radar_width = layout["RADAR_WIDTH"]
    screen_height = HEIGHT

    scale_x = radar_width / WIDTH
    scale_y = screen_height / HEIGHT

    scaled = {}
    for name, pos in FIXES.items():
        scaled[name] = {
            "x": int(pos["x"] * scale_x),
            "y": int(pos["y"] * scale_y)
        }
    return scaled

def calculate_layout(width, height):
    layout = {}

    sidebar_ratio = 0.15
    sidebar_offset_ratio = 0
    bottom_margin_ratio = 0.25
    font_ratio = 0.016 

    layout["SIDEBAR_WIDTH"] = int(width * sidebar_ratio)
    layout["SIDEBAR_OFFSET"] = int(width * sidebar_offset_ratio)
    layout["RADAR_WIDTH"] = width - layout["SIDEBAR_WIDTH"]
    layout["RADAR_CENTER"] = (layout["RADAR_WIDTH"] // 2, height // 2)
    layout["BOTTOM_MARGIN"] = int(height * bottom_margin_ratio)
    layout["FONT_SIZE"] = max(12, int(height * font_ratio))
    layout["RING_SCALE"] = layout["RADAR_WIDTH"] / 1500

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

