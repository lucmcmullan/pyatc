import math, dataclasses, time, random
from typing import List, Optional, TYPE_CHECKING
from atc.utils import (
    normalize_hdg, heading_to_vec, nm_to_px, calculate_layout,
    get_heading_to_fix, distance_to_fix, load_fixes, shortest_turn_dir, px_to_nm
)
from constants import WIDTH, HEIGHT, AIRLINES
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
    dest_hdg: Optional[float] = None
    state: str = "AIRBORNE"
    turn_dir_forced: Optional[str] = None
    climb_rate: int = 1500
    expedite: bool = False
    dest_spd: Optional[int] = None
    msg: str = ""
    command_queue: List[Command] = dataclasses.field(default_factory=list)
    holding: bool = False
    hold_center: Optional[tuple] = None
    hold_timer: float = 0.0
    current_runway: Optional["Runway"] = None
    touchdown_time: Optional[float] = None

    # internal animation vars
    _alt_start: float = dataclasses.field(init=False, default=0)
    _alt_target: float = dataclasses.field(init=False, default=0)
    _alt_start_time: Optional[float] = dataclasses.field(init=False, default=None)
    _alt_duration: float = dataclasses.field(init=False, default=0.0)
    _alt_stabilise_start: Optional[float] = dataclasses.field(init=False, default=None)

    def __post_init__(self):
        self._alt_start = self.alt
        self._alt_target = self.dest_alt
        self._alt_start_time = None
        self._alt_duration = 0.0

    # --- altitude control ---
    def set_altitude_target(self, target_alt: int):
        self._alt_start = self.alt
        self._alt_target = target_alt
        self._alt_start_time = time.time()

        delta = abs(target_alt - self.alt)
        max_climb_rate = 1500 if not self.expedite else 3000
        avg_rate = max_climb_rate * 0.6
        self._alt_duration = max(1.0, (delta / 1000) * 0.5) if delta > 0 else 1.0
        self._alt_stabilise_start = None

    # --- command execution ---
    def execute_command(self, cmd: Command, dt) -> bool:
        assert cmd.value is not None
        if cmd.type == "ALT":
            if cmd.value and cmd.value.isdigit():
                self.dest_alt = int(cmd.value) * 1000
                self.expedite = cmd.extra in ("X", "EX")
            else:
                self.msg = f"{self.callsign}: invalid altitude '{cmd.value}'"
            return True

        elif cmd.type == "HDG":
            if cmd.value and cmd.value.isdigit():
                self.dest_hdg = int(cmd.value)
                self.turn_dir_forced = cmd.extra
            else:
                self.msg = f"{self.callsign}: invalid heading '{cmd.value}'"
            return True

        elif cmd.type == "SPD":
            if cmd.value and cmd.value.isdigit():
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
            fixes = load_fixes()
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
            rw = get_runway(runway_name)  # use singleton registry
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
            self.dest_hdg = rw.bearing  # line up with runway
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
            self.set_altitude_target(0)   # use smooth profile to 0 ft AGL
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
            if self._alt_duration <= 0:
                self._alt_duration = 1.0
            t = min(elapsed / self._alt_duration, 1.0)
            p = 0.6
            t_adj = (math.sin((t - 0.5) * math.pi * p) / math.sin(math.pi * 0.5 * p) + 1) / 2
            factor = 3 * t_adj**2 - 2 * t_adj**3
            self.alt = self._alt_start + (self._alt_target - self._alt_start) * factor

            # stabilisation oscillation
            if t >= 1.0:
                if self._alt_stabilise_start is None:
                    self._alt_stabilise_start = time.time()
                elapsed_since = time.time() - self._alt_stabilise_start
                decay = math.exp(-elapsed_since * 0.8)
                offset = math.sin(elapsed_since * 4) * 20 * decay
                self.alt = self._alt_target + offset
                if decay < 0.05:
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
            self.spd += max(min(diff, 50 * dt), -50 * dt)

        if self.state in ("LANDING", "LANDED") and self.alt <= 20:
            self.spd = max(0, self.spd - 80 * dt)

        # position movement
        dx, dy = heading_to_vec(self.hdg)
        nmps = self.spd / 3600.0
        pxps = nm_to_px(nmps)
        self.x += dx * pxps * dt
        self.y += dy * pxps * dt

        if self.current_runway:
                if self.state == "TAKEOFF":
                    if self.alt >= 100 or self.dest_alt > 0 and self.alt > 0.5 * self.dest_alt:
                        self.current_runway.release()
                        self.current_runway = None
                        self.state = "AIRBORNE"

                elif self.state == "LANDING":
                    if self.alt <= 5:  # touchdown threshold
                        from atc.objects.runway_v2 import get_airport
                        airport = get_airport()
                        assert airport is not None

                        # Register arrival once (if not already)
                        airport.register_arrival(self)

                        # Track touchdown time for rollout
                        if self.touchdown_time is None:
                            self.touchdown_time = time.time()

                        # Once rollout is complete (low speed or >8s on ground)
                        if self.spd < 30 or (time.time() - self.touchdown_time) > 8:
                            self.state = "LANDED"

                            # Release the runway and clear current usage
                            if getattr(self, "current_runway", None):
                                if self.current_runway.active_aircraft == self:
                                    self.current_runway.release()
                                self.current_runway = None

    # --- heading helpers ---
    def turn_towards(self, tgt, dt):
        rate = 3.0
        cur = normalize_hdg(self.hdg)
        tgt = normalize_hdg(tgt)
        sign = 1 if self.turn_dir_forced == "R" else -1 if self.turn_dir_forced == "L" else shortest_turn_dir(cur, tgt)
        diff = abs((tgt - cur + 360) % 360)
        self.hdg = tgt if diff < rate * dt else normalize_hdg(self.hdg + sign * rate * dt)

    def distance_nm(self, other):
        dx, dy = self.x - other.x, self.y - other.y
        return px_to_nm(math.sqrt(dx * dx + dy * dy))

    def vert_sep(self, other):
        return abs(self.alt - other.alt)


# --- random spawner ---
def spawn_random_plane(i: int) -> Aircraft:
    layout = calculate_layout(WIDTH, HEIGHT)
    radar_width = layout["RADAR_WIDTH"]
    radar_height = HEIGHT
    margin = int(50 * (radar_width / 1500))
    edge = random.choice("NSEW")

    if edge == "N":
        x = random.randint(margin, radar_width - margin)
        y = margin
        hdg = random.randint(140, 220)
    elif edge == "S":
        x = random.randint(margin, radar_width - margin)
        y = radar_height - margin
        hdg = random.randint(320, 360) if random.random() < 0.5 else random.randint(0, 40)
    elif edge == "E":
        x = radar_width - margin
        y = random.randint(margin, radar_height - margin)
        hdg = random.randint(220, 320)
    else:
        x = margin
        y = random.randint(margin, radar_height - margin)
        hdg = random.randint(40, 140)
    
    airline_name = random.choice(list(AIRLINES.keys()))
    airline = AIRLINES[airline_name]
    iata = airline["IATA"] if airline["IATA"] is not None else airline["ICAO"]
    flight_number = random.randint(1, 999)
    cs = f"{iata}{flight_number:03d}"
    
    return Aircraft(
        cs,
        x, y,
        normalize_hdg(hdg),
        random.choice([180, 220, 250]),
        random.choice([2000, 4000, 6000]),
        dest_alt=4000
    )