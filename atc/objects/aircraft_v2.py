import math, dataclasses, time, random
from typing import List, Optional, TYPE_CHECKING
from atc.utils import (
    normalize_hdg, heading_to_vec, nm_to_px, calculate_layout,
    get_heading_to_fix, distance_to_fix, load_fixes, shortest_turn_dir, px_to_nm
)
from atc.ai.voice import speak
from constants import (
    WIDTH, HEIGHT, AIRLINES,
    DEFAULT_CLIMB_RATE_FPM, EXPEDITE_CLIMB_RATE_FPM,
    ALTITUDE_INTERPOLATION_MIN_DURATION, ALTITUDE_SMOOTHING_FACTOR,
    ALTITUDE_STABILISE_DECAY, ALTITUDE_STABILISE_FREQ,
    ALTITUDE_STABILISE_AMPLITUDE, ALTITUDE_STABILISE_END_THRESHOLD,
    TURN_RATE_DEG_PER_SEC, SPEED_CHANGE_RATE_KTS_PER_SEC,
    LANDING_DECEL_RATE_KTS_PER_SEC,
    TAKEOFF_RELEASE_ALT_FT, TAKEOFF_RELEASE_RATIO,
    LANDING_TOUCHDOWN_ALT_FT, LANDING_ROLLOUT_MIN_SPEED,
    LANDING_ROLLOUT_MAX_TIME,
    SPAWN_MARGIN_BASE, SPAWN_HEADING_NORTH, SPAWN_HEADING_SOUTH_1,
    SPAWN_HEADING_SOUTH_2, SPAWN_HEADING_EAST, SPAWN_HEADING_WEST,
    SPAWN_SPEEDS, SPAWN_ALTS, DEFAULT_DEST_ALT
)
from .command import Command
from .runway_v2 import get_runway, get_airport

if TYPE_CHECKING:
    from .runway_v2 import Runway


@dataclasses.dataclass
class Aircraft:
    callsign: str
    x: float
    y: float
    hdg: float
    spd: float
    alt: float
    dest_alt: int
    ai_controlled: bool = False
    dest_hdg: Optional[float] = None
    state: str = "AIRBORNE"
    turn_dir_forced: Optional[str] = None
    climb_rate: int = DEFAULT_CLIMB_RATE_FPM
    expedite: bool = False
    dest_spd: Optional[int] = None
    msg: str = ""
    command_queue: List[Command] = dataclasses.field(default_factory=list)
    holding: bool = False
    hold_center: Optional[tuple] = None
    hold_timer: float = 0.0
    current_runway: Optional["Runway"] = None
    touchdown_time: Optional[float] = None

    _alt_start: float = dataclasses.field(init=False, default=0)
    _alt_target: float = dataclasses.field(init=False, default=0)
    _alt_start_time: Optional[float] = dataclasses.field(init=False, default=None)
    _alt_duration: float = dataclasses.field(init=False, default=0.0)
    _alt_stabilise_start: Optional[float] = dataclasses.field(init=False, default=None)
    _ai_next_decision: float = 0.0
    
    def __post_init__(self):
        self._alt_start = self.alt
        self._alt_target = self.dest_alt

    # --- altitude control ---
    def set_altitude_target(self, target_alt: int):
        self._alt_start = self.alt
        self._alt_target = target_alt
        self._alt_start_time = time.time()

        delta = abs(target_alt - self.alt)
        max_climb_rate = DEFAULT_CLIMB_RATE_FPM if not self.expedite else EXPEDITE_CLIMB_RATE_FPM
        avg_rate = max_climb_rate * ALTITUDE_SMOOTHING_FACTOR
        self._alt_duration = max(ALTITUDE_INTERPOLATION_MIN_DURATION, (delta / 1000) * 0.5) if delta > 0 else 1.0
        self._alt_stabilise_start = None

    # --- command execution ---
    def execute_command(self, cmd: Command, dt) -> bool:
        layout = calculate_layout(WIDTH, HEIGHT)
        assert cmd.value is not None
        if cmd.type == "ALT":
            if cmd.value.isdigit():
                self.dest_alt = int(cmd.value) * 1000
                self.expedite = cmd.extra in ("X", "EX")
            else:
                self.msg = f"{self.callsign}: invalid altitude '{cmd.value}'"
            
            return True

        elif cmd.type == "HDG":
            if cmd.value.isdigit():
                self.dest_hdg = int(cmd.value)
                self.turn_dir_forced = cmd.extra
            else:
                self.msg = f"{self.callsign}: invalid heading '{cmd.value}'"
            return True

        elif cmd.type == "SPD":
            if cmd.value.isdigit():
                self.dest_spd = int(cmd.value)
            else:
                self.msg = f"{self.callsign}: invalid speed '{cmd.value}'"
            return True

        elif cmd.type == "HOLD":
            self.holding = True
            self.hold_center = (self.x, self.y)
            self.msg = f"{self.callsign} HOLDING"
            return True

        elif cmd.type == "NAV":
            fixes = load_fixes(layout)
            if cmd.value not in fixes:
                self.msg = f"UNKNOWN FIX {cmd.value}"
                return True
            fix = fixes[cmd.value]
            hdg = get_heading_to_fix(self, fix)
            self.dest_hdg = hdg
            self.msg = f"{self.callsign} CLEARED TO {cmd.value}"
            if distance_to_fix(self, fix) < 12:
                self.msg = f"{self.callsign} ARRIVED {cmd.value}"
            return True

        elif cmd.type == "TAKEOFF":
            runway_name, spd, alt = cmd.value.split(",")
            rw = get_runway(runway_name)
            if not rw:
                self.msg = f"Runway {runway_name} not found"
                return True
            if not rw.is_available():
                self.msg = f"{runway_name} occupied"
                return True

            rw.occupy(self)
            self.current_runway = rw
            self.state = "TAKEOFF"
            self.dest_spd = int(spd)
            self.dest_alt = int(alt)
            self.dest_hdg = rw.bearing
            self.msg = f"{self.callsign} rolling {rw.name}"
            return True

        elif cmd.type == "LAND":
            rw = get_runway(cmd.value)
            if not rw:
                self.msg = f"Runway {cmd.value} not found"
                return True
            if not rw.is_available():
                self.msg = f"{rw.name} occupied"
                return True

            rw.occupy(self)
            self.current_runway = rw
            self.state = "LANDING"
            self.dest_hdg = rw.bearing
            self.dest_spd = 160
            self.set_altitude_target(0)
            self.msg = f"{self.callsign} landing {rw.name}"
            return True

        return True

    def update(self, dt):
        if self.command_queue:
            current = self.command_queue[0]
            done = self.execute_command(current, dt)
            if done:
                self.command_queue.pop(0)

        # altitude interpolation
        if self._alt_start_time is not None:
            elapsed = time.time() - self._alt_start_time
            self._alt_duration = max(self._alt_duration, ALTITUDE_INTERPOLATION_MIN_DURATION)
            t = min(elapsed / self._alt_duration, 1.0)
            p = ALTITUDE_SMOOTHING_FACTOR
            t_adj = (math.sin((t - 0.5) * math.pi * p) / math.sin(math.pi * 0.5 * p) + 1) / 2
            factor = 3 * t_adj**2 - 2 * t_adj**3
            self.alt = self._alt_start + (self._alt_target - self._alt_start) * factor

            # stabilisation oscillation
            if t >= 1.0:
                if self._alt_stabilise_start is None:
                    self._alt_stabilise_start = time.time()
                elapsed_since = time.time() - self._alt_stabilise_start
                decay = math.exp(-elapsed_since * ALTITUDE_STABILISE_DECAY)
                offset = math.sin(elapsed_since * ALTITUDE_STABILISE_FREQ) * ALTITUDE_STABILISE_AMPLITUDE * decay
                self.alt = self._alt_target + offset
                if decay < ALTITUDE_STABILISE_END_THRESHOLD:
                    self.alt = self._alt_target
                    self._alt_start_time = None
                    self._alt_stabilise_start = None
        else:
            rate = self.climb_rate * (2 if self.expedite else 1)
            if self.alt < self.dest_alt:
                self.alt = min(self.dest_alt, self.alt + rate * dt / 60)
            elif self.alt > self.dest_alt:
                self.alt = max(self.dest_alt, self.alt - rate * dt / 60)

        # heading control
        if self.dest_hdg is not None:
            self.turn_towards(self.dest_hdg, dt)

        # speed control
        if self.dest_spd:
            diff = self.dest_spd - self.spd
            self.spd += max(min(diff, SPEED_CHANGE_RATE_KTS_PER_SEC * dt), -SPEED_CHANGE_RATE_KTS_PER_SEC * dt)

        if self.state in ("LANDING", "LANDED") and self.alt <= 20:
            self.spd = max(0, self.spd - LANDING_DECEL_RATE_KTS_PER_SEC * dt)

        # movement
        dx, dy = heading_to_vec(self.hdg)
        nmps = self.spd / 3600.0
        pxps = nm_to_px(nmps)
        self.x += dx * pxps * dt
        self.y += dy * pxps * dt

        # takeoff / landing transitions
        if self.current_runway:
            if self.state == "TAKEOFF":
                if self.alt >= TAKEOFF_RELEASE_ALT_FT or (
                    self.dest_alt > 0 and self.alt > TAKEOFF_RELEASE_RATIO * self.dest_alt
                ):
                    self.current_runway.release()
                    self.current_runway = None
                    self.state = "AIRBORNE"

            elif self.state == "LANDING" and self.alt <= LANDING_TOUCHDOWN_ALT_FT:
                airport = get_airport()
                assert airport is not None
                airport.register_arrival(self)

                if self.touchdown_time is None:
                    self.touchdown_time = time.time()

                if self.spd < LANDING_ROLLOUT_MIN_SPEED or (
                    time.time() - self.touchdown_time > LANDING_ROLLOUT_MAX_TIME
                ):
                    self.state = "LANDED"
                    if getattr(self, "current_runway", None):
                        if self.current_runway.active_aircraft == self:
                            self.current_runway.release()
                        self.current_runway = None

    def turn_towards(self, tgt, dt):
        cur = normalize_hdg(self.hdg)
        tgt = normalize_hdg(tgt)
        sign = (
            1 if self.turn_dir_forced == "R"
            else -1 if self.turn_dir_forced == "L"
            else shortest_turn_dir(cur, tgt)
        )
        diff = abs((tgt - cur + 360) % 360)
        self.hdg = tgt if diff < TURN_RATE_DEG_PER_SEC * dt else normalize_hdg(
            self.hdg + sign * TURN_RATE_DEG_PER_SEC * dt
        )

    def distance_nm(self, other):
        dx, dy = self.x - other.x, self.y - other.y
        return px_to_nm(math.sqrt(dx * dx + dy * dy))

    def vert_sep(self, other):
        return abs(self.alt - other.alt)


def spawn_random_plane(i: int) -> Aircraft:
    layout = calculate_layout(WIDTH, HEIGHT)
    radar_width = layout["RADAR_WIDTH"]
    radar_height = layout["RADAR_HEIGHT"]
    margin = int(SPAWN_MARGIN_BASE * (radar_width / 1500))
    edge = random.choice("NSEW")

    if edge == "N":
        x = random.randint(margin, radar_width - margin)
        y = margin
        hdg = random.randint(*SPAWN_HEADING_NORTH)
    elif edge == "S":
        x = random.randint(margin, radar_width - margin)
        y = radar_height - margin
        hdg = random.randint(*SPAWN_HEADING_SOUTH_1) if random.random() < 0.5 else random.randint(*SPAWN_HEADING_SOUTH_2)
    elif edge == "E":
        x = radar_width - margin
        y = random.randint(margin, radar_height - margin)
        hdg = random.randint(*SPAWN_HEADING_EAST)
    else:
        x = margin
        y = random.randint(margin, radar_height - margin)
        hdg = random.randint(*SPAWN_HEADING_WEST)

    airline_name = random.choice(list(AIRLINES.keys()))
    airline = AIRLINES[airline_name]
    iata = airline["IATA"] or airline["ICAO"]
    flight_number = random.randint(1, 999)
    cs = f"{iata}{flight_number:03d}"

    return Aircraft(
        cs,
        x, y,
        normalize_hdg(hdg),
        random.choice(SPAWN_SPEEDS),
        random.choice(SPAWN_ALTS),
        dest_alt=DEFAULT_DEST_ALT
    )