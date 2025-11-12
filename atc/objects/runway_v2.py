import dataclasses, pygame, time
from atc.utils import normalize_hdg, heading_to_vec, nm_to_px, calculate_layout, load_runways, scale_position
from constants import (
    HEIGHT, WIDTH,
    COLOUR_RUNWAY_BASE, COLOUR_RUNWAY_AVAILABLE, COLOUR_RUNWAY_OCCUPIED, COLOUR_RUNWAY_CLOSED,
    COLOUR_RUNWAY_LABEL,
    RUNWAY_BASE_WIDTH, RUNWAY_ACTIVE_WIDTH,
    RUNWAY_LABEL_OFFSET_X, RUNWAY_LABEL_OFFSET_Y,
    RUNWAY_NAME_OFFSET_X, RUNWAY_NAME_OFFSET_Y,
    RUNWAY_DEFAULT_LENGTH_NM, RUNWAY_SUFFIX_LR, RUNWAY_SUFFIX_MULTI,
    RUNWAY_DEFAULT_STATUS, RUNWAY_OCCUPIED_STATUS, RUNWAY_CLOSED_STATUS,
    AIRPORT_DEFAULT_ICAO, AIRPORT_DEFAULT_NAME
)
from typing import Optional, TYPE_CHECKING
from .airport import Airport

if TYPE_CHECKING:
    from .aircraft_v2 import Aircraft

_RUNWAYS: list["Runway"] = []
_AIRPORTS: list["Airport"] = []


def _build_runways():
    layout = calculate_layout(WIDTH, HEIGHT)

    base_runways = load_runways()

    bearing_groups: dict[int, list[dict]] = {}
    for rw in base_runways:
        bearing = int(round(rw["bearing"] / 10.0)) * 10
        bearing_groups.setdefault(bearing, []).append(rw)

    for bearing, runways in bearing_groups.items():
        count = len(runways)
        if count == 2:
            suffixes = RUNWAY_SUFFIX_LR
        elif count > 2:
            suffixes = RUNWAY_SUFFIX_MULTI[:count]
        else:
            suffixes = [""]
        for rw, suffix in zip(runways, suffixes):
            rw["auto_name"] = f"{int(round(rw['bearing'] / 10)):02d}{suffix}"

    res = []
    for rw in base_runways:
        bearing = rw["bearing"]
        length_nm = rw.get("length_nm", RUNWAY_DEFAULT_LENGTH_NM)

        cx, cy = int(rw["x"] * WIDTH), int(rw["y"] * HEIGHT)

        res.append(Runway(
            name=rw.get("auto_name") or rw.get("name", "RWY_UNKNOWN"),
            x=cx,
            y=cy,
            start=(0, 0),
            end=(0, 0),
            bearing=bearing,
            length_nm=length_nm
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
    length_nm: float = RUNWAY_DEFAULT_LENGTH_NM
    active_aircraft: Optional["Aircraft"] = None
    status: str = RUNWAY_DEFAULT_STATUS
    last_used: float = 0.0
    airport: Optional["Airport"] = None

    def __post_init__(self):
        self.opposite_bearing = normalize_hdg(self.bearing + 180)

    def is_available(self):
        return self.status == RUNWAY_DEFAULT_STATUS and self.active_aircraft is None

    def occupy(self, aircraft: "Aircraft"):
        self.active_aircraft = aircraft
        self.status = RUNWAY_OCCUPIED_STATUS
        self.last_used = time.time()

    def release(self):
        self.active_aircraft = None
        self.status = RUNWAY_DEFAULT_STATUS
        self.last_used = time.time()

    def draw(self, screen, font):
        layout = calculate_layout(*screen.get_size())
        scale = layout["RING_SCALE"]

        cx, cy = scale_position(self.x, self.y, layout)

        half_len_px = nm_to_px(self.length_nm / 2) * scale

        dx, dy = heading_to_vec(self.bearing)
        start = (cx - dx * half_len_px, cy - dy * half_len_px)
        end   = (cx + dx * half_len_px, cy + dy * half_len_px)

        base_w = max(1, int(RUNWAY_BASE_WIDTH * scale))
        active_w = max(1, int(RUNWAY_ACTIVE_WIDTH * scale))
        pygame.draw.line(screen, COLOUR_RUNWAY_BASE, start, end, base_w)

        colour = (COLOUR_RUNWAY_OCCUPIED if self.status == RUNWAY_OCCUPIED_STATUS else
                COLOUR_RUNWAY_CLOSED   if self.status == RUNWAY_CLOSED_STATUS   else
                COLOUR_RUNWAY_AVAILABLE)
        pygame.draw.line(screen, colour, start, end, active_w)

        label_offset_x = int(RUNWAY_LABEL_OFFSET_X * scale)
        label_offset_y = int(RUNWAY_LABEL_OFFSET_Y * scale)
        name_offset_x  = int(RUNWAY_NAME_OFFSET_X  * scale)
        name_offset_y  = int(RUNWAY_NAME_OFFSET_Y  * scale)

        label_a = f"{int(round(self.bearing / 10)) % 36:02d}"
        label_b = f"{int(round(self.opposite_bearing / 10)) % 36:02d}"

        text_a = font.render(label_a, True, colour)
        text_b = font.render(label_b, True, colour)
        screen.blit(text_a, (start[0] + label_offset_x, start[1] + label_offset_y))
        screen.blit(text_b, (end[0]   - 20,            end[1]   + label_offset_x))

        name_text = font.render(self.name, True, COLOUR_RUNWAY_LABEL)
        screen.blit(name_text, (cx + name_offset_x, cy + name_offset_y))


def build_airports():
    global _AIRPORTS
    if _AIRPORTS:
        return _AIRPORTS

    runways = all_runways()
    airport = Airport(icao=AIRPORT_DEFAULT_ICAO, name=AIRPORT_DEFAULT_NAME, runways=runways)

    for rw in runways:
        rw.airport = airport

    _AIRPORTS.append(airport)
    return _AIRPORTS


def get_airport() -> Optional["Airport"]:
    if not _AIRPORTS:
        build_airports()
    return _AIRPORTS[0]