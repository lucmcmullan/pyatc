import dataclasses, pygame, time
from atc.utils import normalize_hdg, heading_to_vec, nm_to_px, calculate_layout, load_runways
from constants import HEIGHT, WIDTH
from typing import Optional, TYPE_CHECKING
from .airport import Airport

if TYPE_CHECKING:
    from .aircraft_v2 import Aircraft

_RUNWAYS: list["Runway"] = []
_AIRPORTS: list["Airport"] = []

def _build_runways():
    layout = calculate_layout(WIDTH, HEIGHT)
    radar_width = layout["RADAR_WIDTH"]
    radar_height = HEIGHT

    base_runways = load_runways()

    # --- Group runways by bearing ---
    bearing_groups: dict[int, list[dict]] = {}
    for rw in base_runways:
        bearing = int(round(rw["bearing"] / 10.0)) * 10  # normalize to nearest 10°
        bearing_groups.setdefault(bearing, []).append(rw)

    # --- Assign unique suffixes (L/R or A/B/C) ---
    for bearing, runways in bearing_groups.items():
        count = len(runways)
        if count == 2:
            suffixes = ["L", "R"]
        elif count > 2:
            suffixes = [chr(ord("A") + i) for i in range(count)]  # A, B, C, D...
        else:
            suffixes = [""]

        for rw, suffix in zip(runways, suffixes):
            rw["auto_name"] = f"{int(round(rw['bearing'] / 10)):02d}{suffix}"

    res = []
    for rw in base_runways:
        bearing = rw["bearing"]
        length_nm = rw.get("length_nm", 2.0)
        half_len = nm_to_px(length_nm / 2)
        cx, cy = int(rw["x"] * radar_width), int(rw["y"] * radar_height)
        dx, dy = heading_to_vec(bearing)
        start = (cx - dx * half_len, cy - dy * half_len)
        end = (cx + dx * half_len, cy + dy * half_len)

        res.append(Runway(
            name = rw.get("auto_name") or rw.get("name", "RWY_UNKNOWN"),  # use auto designation
            x = cx,
            y = cy,
            start = start,
            end = end,
            bearing = bearing,
            length_nm = length_nm
        ))
    return res

def all_runways() -> list["Runway"]:
    global _RUNWAYS
    if not _RUNWAYS:
        _RUNWAYS = _build_runways()
    return _RUNWAYS

def get_runway(name: str) -> Optional["Runway"]:
    return next((r for r in all_runways() if r.name == name), None)

@dataclasses.dataclass
class Runway:
    name: str
    x: int
    y: int
    start: tuple[float, float]
    end: tuple[float, float]
    bearing: int = normalize_hdg(90)
    length_nm: int = 2
    active_aircraft: Optional["Aircraft"] = None
    status: str = "AVAILABLE" # AVAILABLE, OCCUPIED, CLOSED
    last_used: float = 0.0
    airport: Optional["Airport"] = None

    def __post_init__(self):
        self.opposite_bearing = normalize_hdg(self.bearing + 180)

    def is_available(self):
        return self.status == "AVAILABLE" and self.active_aircraft is None
    
    def occupy(self, aircraft: "Aircraft"):
        self.active_aircraft = aircraft
        self.status = "OCCUPIED"
        self.last_used = time.time()

    def release(self):
        self.active_aircraft = None
        self.status = "AVAILABLE"
        self.last_used = time.time()

    def draw(self, screen, font):
        colour = (255, 255, 255)
        if self.status == "OCCUPIED":
            colour = (255, 100, 100)
        elif self.status == "CLOSED":
            colour = (100, 100, 100)

        pygame.draw.line(screen, (180, 180, 180), self.start, self.end, 6)
        pygame.draw.line(screen, colour, self.start, self.end, 2)

        label_a = f"{int(round(self.bearing / 10)) % 36:02d}"
        label_b = f"{int(round(self.opposite_bearing / 10)) % 36:02d}"

        text_a = font.render(label_a, True, colour)
        text_b = font.render(label_b, True, colour)
        
        screen.blit(text_a, (self.start[0] + 10, self.start[1] - 5))
        screen.blit(text_b, (self.end[0] - 20, self.end[1] - 5))

        name_text = font.render(self.name, True, (255, 255, 0))
        screen.blit(name_text, (self.x + 10, self.y + 10))

def build_airports():
    global _AIRPORTS
    if _AIRPORTS:
        return _AIRPORTS
    
    runways = all_runways()
    airport = Airport(icao="EGXX", name="Airport1",runways=runways)

    for rw in runways:
        rw.airport = airport

    _AIRPORTS.append(airport)
    return _AIRPORTS

def get_airport() -> Optional["Airport"]:
    if not _AIRPORTS:
        build_airports()
    return _AIRPORTS[0]