from atc.objects.command import Command
from atc.objects.runway_v2 import get_runway
from atc.utils import convert_to_phraseology, get_callsign_from_iata
from constants import (
    LANDING_HEADING_OFFSET_DEG,
    LANDING_HEIGHT_OFFSET_FT,
    CMD_TURN_TOKENS,
    CMD_TAKEOFF_PARAMS_REQUIRED,
    ALTITUDE_STEP_FT,
    MSG_NO_COMMAND,
    MSG_NO_INPUT,
    MSG_INVALID_TAKEOFF,
    MSG_RUNWAY_NOT_FOUND,
    MSG_RUNWAY_OCCUPIED,
    MSG_NOT_ALIGNED,
    MSG_TOO_HIGH,
    MSG_LAND_CLEARANCE,
    MSG_TAKEOFF_CLEARANCE,
    MSG_HOLD_POS,
    MSG_HOLD_FIX,
    MSG_TAKEOFF_MISSING_PARAMS,
    MSG_LANDING_MISSING_RUNWAY,
)


def _angle_diff(a: float, b: float) -> float:
    """Return the smallest angular difference between two headings."""
    return min((a - b) % 360, (b - a) % 360)

class CommandParser:
    """Handles parsing and processing of ATC-style commands."""

    def parse(self, text: str, planes):
        """Parse controller input string into executable aircraft commands."""
        if not text.strip():
            return [{"callsign": "", "ctrl_msg": MSG_NO_COMMAND, "ack_msg": MSG_NO_INPUT}]

        segments = [seg.strip() for seg in text.split("|") if seg.strip()]
        results = []

        for seg in segments:
            user_took_control = False
            parts = seg.upper().split()
            if not parts:
                continue

            callsign = parts[0]
            aircraft = next((p for p in planes if p.callsign.upper() == callsign.upper()), None)

            if not aircraft:
                results.append({
                    "callsign": callsign,
                    "ctrl_msg": f"{callsign}: NOT FOUND",
                    "ack_msg": f"Unable, {callsign} not found."
                })
                continue

            cmds, ack_segments = self._parse_segment(parts[1:], aircraft)
            
            if cmds:
                aircraft.ai_controlled = False
                user_took_control = True
                
            ctrl_msg, ack_msg = self._build_responses(callsign, cmds, ack_segments)

            if cmds:
                aircraft.command_queue.extend(cmds)

            results.append({
                "callsign": callsign,
                "ctrl_msg": ctrl_msg,
                "ack_msg": ack_msg,
            })

        return results

    def _parse_segment(self, tokens, aircraft):
        """Interpret a single command segment for one aircraft."""
        cmds, ack_segments = [], []
        i = 0

        while i < len(tokens):
            token = tokens[i]

            if token == "C":
                i += 1
                if i >= len(tokens):
                    break
                arg = tokens[i]
                extra = tokens[i + 1] if i + 1 < len(tokens) and tokens[i + 1] in CMD_TURN_TOKENS else None
                if extra:
                    i += 1

                if arg.isdigit() and len(arg) == 3:
                    cmds.append(Command("HDG", arg, extra))
                    turn = "left " if extra == "L" else "right " if extra == "R" else ""
                    ack_segments.append(f"turn {turn}heading {convert_to_phraseology(int(arg), 'heading')}")

                elif arg.isdigit():
                    cmds, ack = self._handle_altitude_command(aircraft, arg, extra)
                    ack_segments.append(ack)

                else:
                    cmds.append(Command("NAV", arg, extra))
                    ack_segments.append(f"cleared direct {arg}")

            elif token == "S":
                if i + 1 < len(tokens):
                    spd = tokens[i + 1]
                    cmds.append(Command("SPD", spd))
                    ack_segments.append(f"speed {convert_to_phraseology(int(spd), 'speed')}")
                    i += 1

            elif token == "H":
                fix = tokens[i + 1] if i + 1 < len(tokens) else None
                cmds.append(Command("HOLD", fix))
                ack_segments.append(MSG_HOLD_FIX.format(fix=fix) if fix else MSG_HOLD_POS)
                if fix:
                    i += 1

            elif token == "T":
                ack, new_cmds, skip = self._handle_takeoff(tokens, i, aircraft)
                ack_segments.append(ack)
                cmds.extend(new_cmds)
                i += skip

            elif token == "L":
                ack, new_cmds, skip = self._handle_landing(tokens, i, aircraft)
                ack_segments.append(ack)
                cmds.extend(new_cmds)
                i += skip

            elif token == "AI":
                mode = None
                if i + 1 < len(tokens):
                    nxt = tokens[i + 1]
                    if nxt in ("ON", "OFF", "1", ):
                        mode = nxt
                        i += 1
                if mode is None:
                    aircraft.ai_controlled = not getattr(aircraft, "ai_controlled", False)
                else:
                    aircraft.ai_controlled = (mode in ("ON", "1"))
                
                ack_segments.append(f"AI {'enabled' if aircraft.ai_controlled else 'disabled'}")
                i += 1
                continue

            i += 1

        return cmds, ack_segments

    def _handle_altitude_command(self, aircraft, arg, extra):
        """Process climb/descend commands."""
        target_alt = int(arg) * ALTITUDE_STEP_FT
        cmd = Command("ALT", arg, extra)
        ex = " expedite" if extra in ("X", "EX") else ""

        if hasattr(aircraft, "alt"):
            if target_alt > aircraft.alt:
                direction = "climb and maintain"
            elif target_alt < aircraft.alt:
                direction = "descend and maintain"
            else:
                direction = "maintain"
        else:
            direction = "climb and maintain"

        spoken_alt = convert_to_phraseology(target_alt, "altitude")
        ack = f"{direction} {spoken_alt}{ex}"

        if hasattr(aircraft, "set_altitude_target"):
            aircraft.set_altitude_target(target_alt)
            aircraft.dest_alt = target_alt

        return [cmd], ack

    def _handle_takeoff(self, tokens, i, aircraft):
        """Handle takeoff clearances."""
        if i + CMD_TAKEOFF_PARAMS_REQUIRED >= len(tokens):
            return MSG_TAKEOFF_MISSING_PARAMS, [], 0

        runway_name, spd, alt = tokens[i + 1:i + 4]
        if not spd.isdigit() or not alt.isdigit():
            return MSG_INVALID_TAKEOFF, [], CMD_TAKEOFF_PARAMS_REQUIRED

        runway = get_runway(runway_name)
        if not runway:
            return MSG_RUNWAY_NOT_FOUND.format(rwy=runway_name), [], CMD_TAKEOFF_PARAMS_REQUIRED
        if not runway.is_available():
            return MSG_RUNWAY_OCCUPIED.format(rwy=runway_name), [], CMD_TAKEOFF_PARAMS_REQUIRED

        cmd = Command("TAKEOFF", f"{runway_name},{spd},{alt}")
        return MSG_TAKEOFF_CLEARANCE.format(rwy=runway_name, alt=alt, spd=spd), [cmd], CMD_TAKEOFF_PARAMS_REQUIRED

    def _handle_landing(self, tokens, i, aircraft):
        """Handle landing clearances."""
        if i + 1 >= len(tokens):
            return MSG_LANDING_MISSING_RUNWAY, [], 0

        runway_name = tokens[i + 1]
        runway = get_runway(runway_name)
        if not runway:
            return MSG_RUNWAY_NOT_FOUND.format(rwy=runway_name), [], 1
        if not runway.is_available():
            return MSG_RUNWAY_OCCUPIED.format(rwy=runway_name), [], 1

        heading_diff = _angle_diff(aircraft.hdg, runway.bearing)
        if heading_diff > LANDING_HEADING_OFFSET_DEG:
            return MSG_NOT_ALIGNED.format(rwy=runway_name), [], 1
        if aircraft.alt > LANDING_HEIGHT_OFFSET_FT:
            return MSG_TOO_HIGH, [], 1

        cmd = Command("LAND", runway_name)
        return MSG_LAND_CLEARANCE.format(rwy=runway_name), [cmd], 1

    def _build_responses(self, callsign, cmds, ack_segments):
        """Create ATC-style control and acknowledgement messages."""
        if not cmds:
            ctrl_msg = f"{callsign}: NO VALID COMMANDS"
            ack_msg = ", ".join(ack_segments).capitalize() if ack_segments else "No response."
            return ctrl_msg, ack_msg

        joined_ack = ", ".join(ack_segments)
        callsign_spoken = get_callsign_from_iata(callsign)
        ack_msg = f"{joined_ack.capitalize()}, {callsign_spoken}"
        ctrl_msg = f"{callsign}: CLEARED {len(cmds)} COMMAND(S)"
        return ctrl_msg, ack_msg