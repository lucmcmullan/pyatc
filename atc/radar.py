import math, pygame, psutil
from atc.utils import heading_to_vec, load_fixes, nm_to_px, wrap_text, calculate_layout
from constants import *

def draw_flight_progress_log(screen, font, planes_or_snapshot, layout=None):
    if not layout:
        layout = calculate_layout(WIDTH, HEIGHT)

    SIDEBAR_WIDTH = layout["SIDEBAR_WIDTH"]
    RADAR_WIDTH = layout["RADAR_WIDTH"]

    panel_w, panel_h = 400, 440
    surf_w, surf_h = screen.get_size()
    panel_x = (surf_w - panel_w) // 2
    panel_y = (surf_h - panel_h) // 2

    pygame.draw.rect(screen, COLOUR_FPL_BG, (panel_x, panel_y, panel_w, panel_h))
    pygame.draw.rect(screen, COLOUR_FPL_BORDER, (panel_x, panel_y, panel_w, panel_h), 1)

    title = font.render("FLIGHT PROGRESS LOG", True, COLOUR_FPL_TITLE)
    screen.blit(title, (panel_x + 10, panel_y + 10))

    expand_icon = pygame.Rect(
        panel_x + panel_w - EXPAND_ICON_OFFSET, panel_y + EXPAND_ICON_PADDING, *EXPAND_ICON_SIZE
    )

    y = panel_y + 35
    for ac in planes_or_snapshot:
        state = ac.get("state", "UNKNOWN").upper()
        bg = {
            "AIRBORNE": COLOUR_STATE_AIRBORNE,
            "CLIMBING": COLOUR_STATE_AIRBORNE,
            "CRUISE": COLOUR_STATE_AIRBORNE,
            "LANDING": COLOUR_STATE_APPROACH,
            "APPROACH": COLOUR_STATE_APPROACH,
            "TAKEOFF": COLOUR_STATE_TAKEOFF,
            "LANDED": COLOUR_STATE_LANDED,
        }.get(state, COLOUR_STATE_UNKNOWN)

        pygame.draw.rect(screen, bg, (panel_x + 5, y, panel_w - 10, FPL_ROW_HEIGHT))
        info = f"{ac['callsign']:8}  {int(ac['alt']):5}ft  {int(ac['spd']):3}kt  {int(ac['hdg']):03d}°"
        txt = font.render(info, True, COLOUR_FPL_TEXT)
        screen.blit(txt, (panel_x + 10, y + 3))
        y += FPL_ROW_HEIGHT + 2
        if y > panel_y + panel_h - FPL_ROW_HEIGHT:
            break

    # Legend
    legend_y = panel_y + panel_h - FPL_LEGEND_HEIGHT
    legend = [
        ("Airborne", COLOUR_STATE_AIRBORNE),
        ("Approach", COLOUR_STATE_APPROACH),
        ("Takeoff", COLOUR_STATE_TAKEOFF),
        ("Landed", COLOUR_STATE_LANDED),
    ]
    for label, color in legend:
        pygame.draw.rect(screen, color, (panel_x + 10, legend_y, 15, 15))
        screen.blit(font.render(label, True, COLOUR_LEGEND_TEXT), (panel_x + 30, legend_y - 2))
        legend_y += 18

    return {"expand_icon": expand_icon}


def draw_aircraft(screen, font, plane, active=False):
    colour = COLOUR_PLANE_ACTIVE if active else COLOUR_PLANE_DEFAULT

    rect = pygame.Surface((PLANE_ICON_SIZE, PLANE_ICON_SIZE), pygame.SRCALPHA)
    rect.fill(colour)
    rotated = pygame.transform.rotate(rect, -plane.hdg)
    rect_rect = rotated.get_rect(center=(plane.x, plane.y))
    screen.blit(rotated, rect_rect.topleft)

    dx, dy = heading_to_vec(plane.hdg)
    end_x = plane.x + dx * PLANE_HEADING_LINE_LENGTH
    end_y = plane.y + dy * PLANE_HEADING_LINE_LENGTH
    pygame.draw.line(screen, colour, (plane.x, plane.y), (end_x, end_y), 2)

    text_callsign = font.render(plane.callsign, True, colour)
    text_info = font.render(f"{int(plane.alt)} {int(plane.spd)} {int(plane.hdg)}", True, colour)
    screen.blit(text_callsign, (plane.x + PLANE_TAG_OFFSET_X, plane.y + PLANE_TAG_OFFSET_Y_CALLSIGN))
    screen.blit(text_info, (plane.x + PLANE_TAG_OFFSET_X, plane.y + PLANE_TAG_OFFSET_Y_INFO))


def draw_performance_menu(screen, font, planes_or_snapshot, *args, **kwargs):
    """
    Draws performance statistics (in main view or detached window).

    planes_or_snapshot:
        • In the main process → list of plane objects
        • In detached window → dict snapshot via update_shared_state()
    """
    snapshot = planes_or_snapshot
    fps = snapshot.get("fps", 0)
    sim_speed = snapshot.get("sim_speed", 1.0)
    cpu_percent = snapshot.get("cpu_percent", 0.0)
    used_mem_mb = snapshot.get("used_mem_mb", 0.0)
    total_mem_mb = snapshot.get("total_mem_mb", 0.0)
    plane_count = snapshot.get("plane_count", 0)
    runway_count = snapshot.get("runway_count", 0)
    occupied = snapshot.get("occupied", "None")

    lines = [
        "=== PERFORMANCE PROFILE ===",
        f"FPS: {fps}",
        f"Simulation speed: {sim_speed:.1f}x",
        f"CPU usage: {cpu_percent:.1f}%",
        f"Memory: {used_mem_mb:.0f} / {total_mem_mb:.0f} MB",
        f"Aircraft active: {plane_count}",
        f"Runways active: {runway_count}",
        f"Runways occupied: {occupied}",
    ]

    width = 360
    height = len(lines) * 22 + 40
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    surf.fill(COLOUR_PERF_BG)

    expand_rect = pygame.Rect(width - EXPAND_ICON_OFFSET, 8, *EXPAND_ICON_SIZE)

    y = 10
    for line in lines:
        surf.blit(font.render(line, True, COLOUR_PERF_TEXT), (10, y))
        y += 22

    screen.blit(surf, (10, 10))
    return {"expand_icon": expand_rect.move(10, 10)}


def draw_radar(screen, planes, font, messages, conflicts,
               radio_log=None, active_cs=None, selected_plane=None, radio_scroll=0,
               runways=None):

    layout = calculate_layout(WIDTH, HEIGHT)
    RADAR_WIDTH = layout["RADAR_WIDTH"]
    RADAR_CENTER = layout["RADAR_CENTER"]
    SIDEBAR_WIDTH = layout["SIDEBAR_WIDTH"]
    SIDEBAR_OFFSET = layout["SIDEBAR_OFFSET"]
    sidebar_x = RADAR_WIDTH - SIDEBAR_OFFSET

    screen.fill(COLOUR_RADAR_BG)

    if runways:
        for rw in runways:
            rw.draw(screen, font)

    # Fix rings and grid
    fixes = load_fixes()
    for name, position in fixes.items():
        x, y = position["x"], position["y"]
        scale = position.get("ring_scale", 1.0)

        for nm in range(*RADAR_FIX_RING_SPACING_NM):
            pixel = int(nm_to_px(nm) * scale)
            pygame.draw.circle(screen, COLOUR_FIX_RING, (x, y), pixel, 1)
            screen.blit(font.render(f"{nm}", True, COLOUR_FIX_TEXT),
                        (x + pixel + 4, y - int(8 * scale)))

        for deg in range(0, 360, RADAR_HEADING_INTERVAL_DEG):
            rad = math.radians(deg)
            dx = math.sin(rad) * nm_to_px(RADAR_LINE_RANGE_NM) * scale
            dy = -math.cos(rad) * nm_to_px(RADAR_LINE_RANGE_NM) * scale
            pygame.draw.line(screen, (60, 60, 120), (x, y), (x + dx, y + dy))

        pygame.draw.circle(screen, COLOUR_FIX_CENTER_OUTER, (x, y), int(5 * scale))
        pygame.draw.circle(screen, COLOUR_FIX_CENTER_INNER, (x, y), int(2 * scale))
        screen.blit(font.render(name, True, COLOUR_FIX_LABEL),
                    (x + int(10 * scale), y - int(10 * scale)))

    for radius in range(RADAR_RING_SPACING, RADAR_RING_MAX_RADIUS, RADAR_RING_SPACING):
        pygame.draw.circle(screen, COLOUR_RADAR_GRID, RADAR_CENTER, radius, 1)

    pygame.draw.line(screen, COLOUR_RADAR_GRID, (RADAR_CENTER[0], 0), (RADAR_CENTER[0], HEIGHT), 1)
    pygame.draw.line(screen, COLOUR_RADAR_GRID, (0, RADAR_CENTER[1]), (RADAR_WIDTH, RADAR_CENTER[1]), 1)

    for plane in planes:
        draw_aircraft(screen, font, plane, active=(plane.callsign == active_cs))

    y = 5
    for a, b, lat, vert in conflicts:
        msg = f"CONFLICT {a.callsign}-{b.callsign} {lat:.1f}NM {vert:.0f}FT"
        screen.blit(font.render(msg, True, COLOUR_CONFLICT), (5, y))
        y += 18

    pygame.draw.rect(screen, COLOUR_SIDEBAR_BG, (sidebar_x, 0, SIDEBAR_WIDTH, HEIGHT))
    pygame.draw.line(screen, COLOUR_SIDEBAR_BORDER, (sidebar_x, 0), (sidebar_x, HEIGHT), 1)

    # Radio / Log sidebar
    display_plane = selected_plane or next((p for p in planes if p.callsign == active_cs), None)
    if display_plane:
        cs = display_plane.callsign
        screen.blit(font.render(f"ACTIVE: {cs}", True, COLOUR_MSG_TITLE), (sidebar_x + 10, 10))

        log = radio_log.get(cs, []) if radio_log else []
        visible_lines = 30
        y = 40

        if not log:
            screen.blit(font.render("(no messages yet)", True, COLOUR_MSG_PLACEHOLDER),
                        (sidebar_x + 10, y))
        else:
            start = max(0, len(log) - visible_lines - radio_scroll)
            end = max(0, len(log) - radio_scroll)
            subset = log[start:end]

            for line in subset:
                color = COLOUR_MSG_CTRL if line.startswith("CTRL") else COLOUR_MSG_TEXT
                for wrapped in wrap_text(line, font, SIDEBAR_WIDTH - 25):
                    screen.blit(font.render(wrapped, True, color), (sidebar_x + 10, y))
                    y += 18

            if len(log) > visible_lines:
                total = len(log) - visible_lines
                bar_h = max(20, int(200 * (visible_lines / len(log))))
                bar_y = int(40 + (radio_scroll / total) * (200 - bar_h))
                pygame.draw.rect(screen, COLOUR_MSG_SCROLLBAR,
                                 (sidebar_x + SIDEBAR_WIDTH - 15, bar_y, 8, bar_h))
    else:
        screen.blit(font.render("Click a plane to view log", True, COLOUR_MSG_HINT),
                    (sidebar_x + 10, 10))

    return