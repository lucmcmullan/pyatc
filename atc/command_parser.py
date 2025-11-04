from atc.objects.command import Command
from atc.objects.runway_v2 import get_runway
from atc.utils import convert_to_phraseology
from constants import LANDING_HEADING_OFFSET_DEG, LANDING_HEIGHT_OFFSET_FT

def _angle_diff(a, b): return min((a - b) % 360, (b - a) % 360)

class CommandParser:
    def parse(self, text: str, planes):
        if not text.strip():
            return "NO COMMAND", None
        
        segments = [seg.strip() for seg in text.split("|") if seg.strip()]

        overall_ctrl_messages = []
        overall_acknowledge_messages = []

        for seg in segments:
            parts = seg.upper().split()
            if not parts:
                continue

            cs = parts[0]
            ac = next((p for p in planes if p.callsign.upper() == cs.upper()), None)
            if not ac:
                overall_ctrl_messages.append(f"{cs} NOT FOUND")
                continue

            cmds = []
            ack_segments = []

            i = 1

            while i < len(parts):
                token = parts[i]

                if token == "C":
                    i += 1
                    if i >= len(parts):
                        break
                    arg = parts[i]
                    extra = None
                    if i + 1 < len(parts) and parts[i + 1] in ("L", "R", "X", "EX"):
                        extra = parts[i + 1]
                        i += 1

                    # Heading
                    if arg.isdigit() and len(arg) == 3:
                        cmds.append(Command("HDG", arg, extra))
                        heading_phrase = convert_to_phraseology(int(arg), "heading")
                        turn_phrase = ""
                        if extra in ("L", "R"):
                            turn_phrase = "left " if extra == "L" else "right "
                        ack_segments.append(f"turn {turn_phrase}heading {heading_phrase}")

                    # Altitude
                    elif arg.isdigit():
                        target_alt = int(arg) * 1000
                        cmds.append(Command("ALT", arg, extra))

                        if hasattr(ac, "alt"):
                            if target_alt > ac.alt:
                                direction = "climb and maintain"
                            elif target_alt < ac.alt:
                                direction = "descend and maintain"
                            else:
                                direction = "maintain"
                        else:
                            direction = "climb and maintain"

                        ex = " expedite" if extra in ("X", "EX") else ""
                        spoken_alt = convert_to_phraseology(target_alt, "altitude")
                        ack_segments.append(f"{direction} {spoken_alt}{ex}")

                        # Apply change immediately
                        if hasattr(ac, "set_altitude_target"):
                            ac.set_altitude_target(target_alt)
                            ac.dest_alt = target_alt

                    # Navigation fix
                    else:
                        cmds.append(Command("NAV", arg, extra))
                        ack_segments.append(f"cleared direct {arg}")

                # Speed
                elif token == "S":
                    i += 1
                    if i < len(parts):
                        spd = parts[i]
                        cmds.append(Command("SPD", spd))
                        spoken_spd = convert_to_phraseology(int(spd), "speed")
                        ack_segments.append(f"speed {spoken_spd}")

                # Hold
                elif token == "H":
                    i += 1
                    fix = parts[i] if i < len(parts) else None
                    cmds.append(Command("HOLD", fix))
                    if fix:
                        ack_segments.append(f"hold at {fix}")
                    else:
                        ack_segments.append("hold position")

                elif token == "T":  # T RWY SPEED ALT
                    if i + 3 < len(parts):
                        runway_name = parts[i + 1]
                        spd = parts[i + 2]
                        alt = parts[i + 3]
                        if not spd.isdigit() or not alt.isdigit():
                            ack_segments.append("unable, invalid takeoff parameters")
                            i += 1
                            continue
                        rw = get_runway(runway_name)  # singleton
                        if not rw:
                            ack_segments.append(f"unable, runway {runway_name} not found")
                            i += 3
                            continue
                        if not rw.is_available():
                            ack_segments.append(f"unable, {runway_name} occupied")
                            i += 3
                            continue
                        cmds.append(Command("TAKEOFF", f"{runway_name},{spd},{alt}"))
                        ack_segments.append(
                            f"cleared for takeoff runway {runway_name}, "
                            f"climb to {alt} feet, maintain {spd} knots"
                        )
                        i += 3
                    else:
                        ack_segments.append("takeoff clearance missing parameters")

                elif token == "L":  # Landing clearance
                    i += 1
                    if i < len(parts):
                        runway_name = parts[i]
                        rw = get_runway(runway_name)
                        if not rw:
                            ack_segments.append(f"unable, runway {runway_name} not found")
                        else:
                            hdg_diff = _angle_diff(ac.hdg, rw.bearing)
                            if hdg_diff > LANDING_HEADING_OFFSET_DEG:
                                ack_segments.append(f"unable, not aligned for {runway_name}")
                            elif ac.alt > LANDING_HEIGHT_OFFSET_FT:
                                ack_segments.append(f"unable, too high for approach")
                            elif not rw.is_available():
                                ack_segments.append(f"unable, {runway_name} occupied")
                            else:
                                cmds.append(Command("LAND", runway_name))
                                ack_segments.append(f"cleared to land runway {runway_name}")
                    else:
                        ack_segments.append("landing clearance missing runway")
                i += 1
            
            if cmds:
                from atc.utils import get_callsign_from_iata
                ac.command_queue.extend(cmds)
                joined_segments = ", ".join(ack_segments)
                spoken = get_callsign_from_iata(cs)
                ack_msg = f"{joined_segments.capitalize()}, {spoken}"
                ctrl_msg = f"{ac.callsign}: CLEARED {len(cmds)} COMMAND(S)"
            else:
                ctrl_msg = f"{cs}: NO VALID COMMANDS"
                # even if no valid cmds, still send a "negative" ack
                ack_msg = ", ".join(ack_segments).capitalize() if ack_segments else "No response."

            overall_ctrl_messages.append(ctrl_msg)
            overall_acknowledge_messages.append(ack_msg)

        # --- simplified result packaging ---
        results = []
        for cs, ctrl_msg, ack_msg in zip(
            [seg.split()[0] for seg in segments],
            overall_ctrl_messages,
            overall_acknowledge_messages,
        ):
            results.append({
                "callsign": cs.upper(),
                "ctrl_msg": ctrl_msg,
                "ack_msg": ack_msg,
            })

        return results