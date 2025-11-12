import math, dataclasses, time, random, json, os
from typing import List, Optional, TYPE_CHECKING
from atc.utils import (
    normalize_hdg, heading_to_vec, nm_to_px, calculate_layout,
    get_heading_to_fix, distance_to_fix, load_fixes, shortest_turn_dir, px_to_nm
)
from atc.ai.voice import speak
from constants import PERF_DATA_DIR, PLANE_TYPES
from atc.utils import isa_density_at_alt_ft, interp_curve_xy
from constants import (
    WIDTH, HEIGHT, AIRLINES,
    DEFAULT_CLIMB_RATE_FPM, EXPEDITE_CLIMB_RATE_FPM,
    ALTITUDE_INTERPOLATION_MIN_DURATION, ALTITUDE_SMOOTHING_FACTOR,
    ALTITUDE_STABILISE_DECAY, ALTITUDE_STABILISE_FREQ,
    ALTITUDE_STABILISE_AMPLITUDE, ALTITUDE_STABILISE_END_THRESHOLD,
    TURN_RATE_DEG_PER_SEC, SPEED_CHANGE_RATE_KTS_PER_SEC,
    LANDING_DECEL_RATE_KTS_PER_SEC, RUNWAY_SPAWN_PROBABILITY,
    TAKEOFF_RELEASE_ALT_FT, TAKEOFF_RELEASE_RATIO, RUNWAYS,
    LANDING_TOUCHDOWN_ALT_FT, LANDING_ROLLOUT_MIN_SPEED,
    LANDING_ROLLOUT_MAX_TIME, COMMAND_DELAY_RANGE, RUNWAY_SPAWN_ALT_FT,
    SPAWN_MARGIN_BASE, SPAWN_HEADING_NORTH, SPAWN_HEADING_SOUTH_1,
    SPAWN_HEADING_SOUTH_2, SPAWN_HEADING_EAST, SPAWN_HEADING_WEST,
    SPAWN_SPEEDS, SPAWN_ALTS, DEFAULT_DEST_ALT
)
from .command import Command
from .runway_v2 import get_runway, get_airport, all_runways

if TYPE_CHECKING:
    from .runway_v2 import Runway

@dataclasses.dataclass
class PerformanceProfile:
    icao: str
    mass: dict
    thrust: dict
    drag: dict
    fuel: dict
    performance: dict
    limits: dict = dataclasses.field(default_factory=dict)
    atmosphere: dict = dataclasses.field(default_factory=dict)

    @staticmethod
    def load_from_json(path: str) -> Optional["PerformanceProfile"]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PerformanceProfile(
                icao=data.get("icao", "UNKNOWN"),
                mass=data.get("mass", {}),
                thrust=data.get("thrust", {}),
                drag=data.get("drag", {}),
                fuel=data.get("fuel", {}),
                performance=data.get("performance", {}),
                limits=data.get("limits", {}),
                atmosphere=data.get("atmosphere", {}),
            )
        except Exception:
            return None

class PhysicsEngine:
    def __init__(self, profile: PerformanceProfile):
        self.p = profile

    def available_thrust_kn(self, alt_ft: float) -> float:
        pts = self.p.thrust.get("available", [])
        if not pts:
            return 0.0
        thrust_key = next((k for k in pts[0].keys() if k.endswith("kn")), "thrust_kn")
        return interp_curve_xy(pts, alt_ft, "alt_ft", thrust_key) or 0.0

    def fuel_flow_kg_per_hr(self, thrust_pct: float) -> float:
        pts = self.p.fuel.get("burn_kg_per_hr_vs_thrust", [])
        return interp_curve_xy(pts, thrust_pct, "thrust_pct", "kg_per_hr") or 0.0

    def roc_fpm(self, weight_kg: float) -> float:
        pts = self.p.performance.get("roc_fpm_vs_weight", [])
        return interp_curve_xy(pts, weight_kg, "weight_kg", "roc_fpm") or 0.0

    def rod_fpm(self, weight_kg: float) -> float:
        pts = self.p.performance.get("rod_fpm_vs_weight", [])
        return interp_curve_xy(pts, weight_kg, "weight_kg", "rod_fpm") or 0.0

@dataclasses.dataclass
class Aircraft:
    callsign: str
    x: float
    y: float
    hdg: float
    spd: float
    alt: float
    dest_alt: int
    aircraft_type: Optional[str] = None
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
    hold_timer: float = 0.0
    pending_command_timer: float = 0.0
    on_runway: bool = False
    assigned_runway: Optional["Runway"] = None
    altitude_history: list = dataclasses.field(default_factory=list)
    history_timer: float = 0.0
    HISTORY_INTERVAL: float = 1.0
    HISTORY_LIMIT_S: float = 600.0 

    _alt_start: float = dataclasses.field(init=False, default=0)
    _alt_target: float = dataclasses.field(init=False, default=0)
    _alt_start_time: Optional[float] = dataclasses.field(init=False, default=None)
    _alt_duration: float = dataclasses.field(init=False, default=0.0)
    _alt_stabilise_start: Optional[float] = dataclasses.field(init=False, default=None)
    _ai_next_decision: float = 0.0
    
    def __post_init__(self):
        self._alt_start = self.alt
        self._alt_target = self.dest_alt

        # === Load aircraft performance profile ===
        self._use_new_physics = False
        self.aircraft_type = getattr(self, "aircraft_type", None)

        try:
            if self.aircraft_type:
                # Build absolute path relative to this file
                base_dir = os.path.dirname(os.path.abspath(__file__))
                perf_dir = os.path.abspath(os.path.join(base_dir, "..", "data", "performance"))
                path = os.path.join(perf_dir, f"{self.aircraft_type}.json")

                # Case-insensitive fallback
                if not os.path.isfile(path):
                    lower_path = os.path.join(perf_dir, f"{self.aircraft_type.lower()}.json")
                    if os.path.isfile(lower_path):
                        path = lower_path

                if os.path.isfile(path):
                    profile = PerformanceProfile.load_from_json(path)
                    if profile:
                        self._perf_profile = profile
                        self._physics = PhysicsEngine(profile)

                        # --- Runtime parameters ---
                        empty_kg = profile.mass.get("empty_kg", 0)
                        self.fuel_capacity_kg = profile.mass.get("fuel_capacity_kg", 10000)
                        self.fuel_kg = min(self.fuel_capacity_kg, 0.5 * self.fuel_capacity_kg)
                        self.weight_kg = empty_kg + self.fuel_kg
                        self.flap_state = 0
                        self.gear_down = False
                        self.thrust_pct = 60.0
                        self._use_new_physics = True
                        print(f"[INFO] Loaded performance profile for {self.aircraft_type}")
                    else:
                        print(f"[WARN] Failed to parse JSON for {self.aircraft_type}")
                else:
                    print(f"[WARN] No JSON found for {self.aircraft_type} at {path}")
            else:
                print(f"[WARN] Aircraft type not set for {self.callsign}")
        except Exception as e:
            print(f"[ERROR] Performance load failed for {self.callsign}: {e}")

    def set_altitude_target(self, target_alt: int):
        self._alt_start = self.alt
        self._alt_target = target_alt
        self._alt_start_time = time.time()

        delta = abs(target_alt - self.alt)
        max_climb_rate = DEFAULT_CLIMB_RATE_FPM if not self.expedite else EXPEDITE_CLIMB_RATE_FPM
        self._alt_duration = max(ALTITUDE_INTERPOLATION_MIN_DURATION, (delta / 1000) * 0.5) if delta > 0 else 1.0
        self._alt_stabilise_start = None

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

            if self.pending_command_timer <= 0:
                self.pending_command_timer = random.uniform(*COMMAND_DELAY_RANGE)
            else:
                self.pending_command_timer -= dt
                if self.pending_command_timer > 0:
                    return

            done = self.execute_command(current, dt)
            if done:
                self.command_queue.pop(0)
                self.pending_command_timer = 0.0

        if self.on_runway and self.state in ("TAKEOFF_PENDING", "ON_RUNWAY"):
            self.alt = RUNWAY_SPAWN_ALT_FT
            self.spd = 0
            return

        if self._alt_start_time is not None:
            elapsed = time.time() - self._alt_start_time
            self._alt_duration = max(self._alt_duration, ALTITUDE_INTERPOLATION_MIN_DURATION)
            t = min(elapsed / self._alt_duration, 1.0)
            p = ALTITUDE_SMOOTHING_FACTOR
            t_adj = (math.sin((t - 0.5) * math.pi * p) / math.sin(math.pi * 0.5 * p) + 1) / 2
            factor = 3 * t_adj**2 - 2 * t_adj**3
            self.alt = self._alt_start + (self._alt_target - self._alt_start) * factor

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

        if self.dest_hdg is not None:
            self.turn_towards(self.dest_hdg, dt)

        if self.dest_spd is not None and not getattr(self, "_use_new_physics", False):
            diff = self.dest_spd - self.spd
            self.spd += max(min(diff, SPEED_CHANGE_RATE_KTS_PER_SEC * dt), -SPEED_CHANGE_RATE_KTS_PER_SEC * dt)

        if getattr(self, "_use_new_physics", False):
            self._physics_update(dt)

        if self.state in ("LANDING", "LANDED") and self.alt <= 20:
            self.spd = max(0, self.spd - LANDING_DECEL_RATE_KTS_PER_SEC * dt)

        dx, dy = heading_to_vec(self.hdg)
        nmps = self.spd / 3600.0
        pxps = nm_to_px(nmps)
        self.x += dx * pxps * dt
        self.y += dy * pxps * dt

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

        if getattr(self, "_use_new_physics", False):
            self.history_timer += dt
            if self.history_timer >= self.HISTORY_INTERVAL:
                self.history_timer = 0.0
                self.altitude_history.append((time.time(), self.alt))
                # Trim history older than HISTORY_LIMIT_S
                cutoff = time.time() - self.HISTORY_LIMIT_S
                self.altitude_history = [
                    (t, a) for (t, a) in self.altitude_history if t >= cutoff
                ]

    def _physics_update(self, dt: float):
        target_spd = self.dest_spd if self.dest_spd is not None else self.spd
        spd_err = (target_spd - self.spd)
        self.thrust_pct = max(0.0, min(100.0, getattr(self, "thrust_pct", 60.0) + 0.5 * spd_err * dt))

        # Atmosphere & thrust
        qnh = self._perf_profile.atmosphere.get("qnh_hpa", 1013.25)
        isa_dev = self._perf_profile.atmosphere.get("isa_deviation_c", 0.0)
        rho = isa_density_at_alt_ft(self.alt, qnh, isa_dev)

        thrust_available_kn = self._physics.available_thrust_kn(self.alt)
        thrust_kn = thrust_available_kn * (self.thrust_pct / 100.0)

        # Drag (quadratic) with flap/gear modifiers
        base_cd = self._perf_profile.drag.get("base_cd", 0.03)
        gear_cd = self._perf_profile.drag.get("gear_cd", 0.02) if getattr(self, "gear_down", False) else 0.0
        flap_cd = 0.0
        for f in self._perf_profile.drag.get("flaps", []):
            if f.get("state") == getattr(self, "flap_state", 0):
                flap_cd = f.get("cd", 0.0)
                break
        cd = base_cd + gear_cd + flap_cd

        # Convert speed (kts) to m/s
        v_ms = max(0.0, self.spd) * 0.514444
        area_ref = 122.0  # m^2 typical narrowbody; tune per-type in future
        drag_n = 0.5 * rho * (v_ms ** 2) * cd * area_ref
        thrust_n = thrust_kn * 1000.0

        # Longitudinal acceleration (very simplified)
        acc_ms2 = (thrust_n - drag_n) / max(1.0, self.weight_kg)
        acc_ms2 = max(-5.0, min(5.0, acc_ms2))  # clamp to keep sim stable

        # Update speed (m/s -> kts)
        self.spd = max(0.0, self.spd + (acc_ms2 * 1.94384) * dt)

        # Vertical rate from performance tables based on current weight and target altitude
        if self.dest_alt is not None and abs(self.dest_alt - self.alt) > 50:
            climbing = self.dest_alt > self.alt
            if climbing:
                vs_fpm = self._physics.roc_fpm(self.weight_kg)
            else:
                vs_fpm = -self._physics.rod_fpm(self.weight_kg)
        else:
            vs_fpm = 0.0

        # Integrate altitude and clamp to target if overshoot
        self.alt += vs_fpm * dt / 60.0
        if (vs_fpm > 0 and self.alt > self.dest_alt) or (vs_fpm < 0 and self.alt < self.dest_alt):
            self.alt = float(self.dest_alt)

        # Fuel burn
        ff_kg_hr = self._physics.fuel_flow_kg_per_hr(self.thrust_pct)
        burned = ff_kg_hr * dt / 3600.0
        self.fuel_kg = max(0.0, self.fuel_kg - burned)

        # Update gross weight
        empty_kg = self._perf_profile.mass.get("empty_kg", 0)
        self.weight_kg = empty_kg + self.fuel_kg

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
    """
    Spawns aircraft either along the radar edge (normal) or occasionally
    directly on a runway, ready to request takeoff.
    """
    layout = calculate_layout(WIDTH, HEIGHT)
    radar_width = layout["RADAR_WIDTH"]
    radar_height = layout["RADAR_HEIGHT"]
    margin = int(SPAWN_MARGIN_BASE * (radar_width / 1500))
    edge_offset = int(margin * 0.8)

    spawn_on_runway = random.random() < RUNWAY_SPAWN_PROBABILITY

    # ======================================================
    # 🛫 1️⃣  Get real runway objects if we’re spawning on one
    # ======================================================
    if spawn_on_runway:
        available_runways = all_runways()
        if not available_runways:
            spawn_on_runway = False
        else:
            rwy_obj = random.choice(available_runways)

    # ======================================================
    # 🛫 2️⃣  Runway-based spawn logic
    # ======================================================
    if spawn_on_runway:
        # Use pre-built, scaled runway object
        cx, cy = rwy_obj.x, rwy_obj.y
        bearing_rad = math.radians(rwy_obj.bearing)
        half_len_px = nm_to_px(rwy_obj.length_nm) / 2

        # Spawn along runway centerline, near threshold
        spawn_dist = half_len_px * 0.9
        x = cx - math.sin(bearing_rad) * spawn_dist
        y = cy + math.cos(bearing_rad) * spawn_dist

        # Tiny lateral offset (± few px) for variety
        lateral = random.uniform(-8, 8)
        x += math.cos(bearing_rad) * lateral
        y += math.sin(bearing_rad) * lateral

        hdg = int(rwy_obj.bearing)
        alt = RUNWAY_SPAWN_ALT_FT
        spd = 0
        on_runway = True
        assigned_runway = rwy_obj.name

        # Optional: flip direction 50% of time (use reciprocal threshold)
        if random.random() < 0.5:
            hdg = (hdg + 180) % 360
            x = cx + math.sin(bearing_rad) * spawn_dist
            y = cy - math.cos(bearing_rad) * spawn_dist

    # ======================================================
    # ✈️ 3️⃣  Normal (airborne) spawn fallback
    # ======================================================
    else:
        edge = random.choice("NSEW")
        if edge == "N":
            x = random.randint(margin, radar_width - margin)
            y = -edge_offset
            hdg = random.randint(*SPAWN_HEADING_NORTH)
        elif edge == "S":
            x = random.randint(margin, radar_width - margin)
            y = radar_height + edge_offset
            hdg = random.randint(*SPAWN_HEADING_SOUTH_1) if random.random() < 0.5 else random.randint(*SPAWN_HEADING_SOUTH_2)
        elif edge == "E":
            x = radar_width + edge_offset
            y = random.randint(margin, radar_height - margin)
            hdg = random.randint(*SPAWN_HEADING_EAST)
        else:
            x = -edge_offset
            y = random.randint(margin, radar_height - margin)
            hdg = random.randint(*SPAWN_HEADING_WEST)
        alt = random.choice(SPAWN_ALTS)
        spd = random.choice(SPAWN_SPEEDS)
        on_runway = False
        assigned_runway = None

    # ======================================================
    # 🧠 4️⃣  Aircraft creation + state setup
    # ======================================================
    airline_name = random.choice(list(AIRLINES.keys()))
    airline = AIRLINES[airline_name]
    iata = airline["IATA"] or airline["ICAO"]
    flight_number = random.randint(1, 999)
    cs = f"{iata}{flight_number:03d}"

    plane = Aircraft(
        cs,
        x, y,
        normalize_hdg(hdg),
        spd,
        alt,
        dest_alt=DEFAULT_DEST_ALT,
        aircraft_type=random.choice(PLANE_TYPES)
    )

    plane.on_runway = on_runway
    plane.assigned_runway = assigned_runway

    if plane.on_runway:
        plane.state = "TAKEOFF_PENDING"
        plane.dest_alt = RUNWAY_SPAWN_ALT_FT
    else:
        plane.state = "AIRBORNE"

    return plane