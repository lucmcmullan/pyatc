import math, pygame
from atc.utils import heading_to_vec, load_fixes, nm_to_px, wrap_text, calculate_layout, scale_position
from constants import *

def draw_flight_progress_log(screen, font, planes_or_snapshot, layout=None):
    if not layout:
        layout = calculate_layout(WIDTH, HEIGHT)

    panel_w, panel_h = 400, 440
    surf_w, surf_h = screen.get_size()
    panel_x = (surf_w - panel_w) // 2
    panel_y = (surf_h - panel_h) // 2

    pygame.draw.rect(screen, COLOUR_FPL_BG, (panel_x, panel_y, panel_w, panel_h))
    pygame.draw.rect(screen, COLOUR_FPL_BORDER, (panel_x, panel_y, panel_w, panel_h), 1)

    title = font.render("FLIGHT PROGRESS LOG", True, COLOUR_FPL_TITLE)
    screen.blit(title, (panel_x + 10, panel_y + 10))

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

    return


def draw_aircraft(screen, font, plane, active=False, layout=None):
    """
    Draw aircraft icon, heading line, and labels — all scaled to current layout.
    Keeps aircraft visible and proportionally positioned when the window size changes.
    """
    from atc.utils import scale_position

    if layout is None:
        layout = calculate_layout(*screen.get_size())

    x, y = scale_position(plane.x, plane.y, layout)
    scale = layout["RING_SCALE"]

    if plane.ai_controlled:
        colour = (100, 100, 255)
    elif active:
        colour = COLOUR_PLANE_ACTIVE
    else:
        colour = COLOUR_PLANE_DEFAULT

    icon_size = max(2, int(PLANE_ICON_SIZE * scale))
    heading_line_len = int(PLANE_HEADING_LINE_LENGTH * scale)

    rect = pygame.Surface((icon_size, icon_size), pygame.SRCALPHA)
    rect.fill(colour)
    rotated = pygame.transform.rotate(rect, -plane.hdg)
    rect_rect = rotated.get_rect(center=(x, y))
    screen.blit(rotated, rect_rect.topleft)

    dx, dy = heading_to_vec(plane.hdg)
    end_x = x + dx * heading_line_len
    end_y = y + dy * heading_line_len
    pygame.draw.line(screen, colour, (x, y), (end_x, end_y), 2)

    topline_const = f"{plane.callsign} {plane.state}"
    bottomline_const = f"{int(plane.alt)} {int(plane.spd)} {int(plane.hdg)}"

    text_topline = font.render(topline_const, True, colour)
    text_bottomline = font.render(bottomline_const, True, colour)

    tag_offset_x = int(PLANE_TAG_OFFSET_X * scale)
    tag_offset_y_call = int(PLANE_TAG_OFFSET_Y_CALLSIGN * scale)
    tag_offset_y_info = int(PLANE_TAG_OFFSET_Y_INFO * scale)

    screen.blit(text_topline, (x + tag_offset_x, y + tag_offset_y_call))
    screen.blit(text_bottomline, (x + tag_offset_x, y + tag_offset_y_info))

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


    y = 10
    for line in lines:
        surf.blit(font.render(line, True, COLOUR_PERF_TEXT), (10, y))
        y += 22

    screen.blit(surf, (10, 10))
    return

def draw_conflict_indicator(a, b, lat, vert, screen, font, radar_rect, cy):
    msg = f"CONFLICT {a.callsign}-{b.callsign} {lat:.1f}NM {vert:.0f}FT"
    screen.blit(font.render(msg, True, COLOUR_CONFLICT), (radar_rect.left + 5, cy))

def draw_radar(screen, planes, font, conflicts,
               radio_log=None, active_cs=None, selected_plane=None, radio_scroll=0,
               runways=None):

    window_w, window_h = screen.get_size()
    layout = calculate_layout(window_w, window_h)

    radar_rect = layout["RADAR_RECT"]
    sidebar_rect = layout["SIDEBAR_RECT"]
    radar_center = layout["RADAR_CENTER"]

    screen.fill(COLOUR_RADAR_BG, radar_rect)

    if runways:
        for rw in runways:
            rw.draw(screen, font)

    fixes = load_fixes(layout)
    for name, position in fixes.items():
        x, y = position["x"], position["y"]
        scale = position.get("ring_scale", 1.0)

        for nm in range(*RADAR_FIX_RING_SPACING_NM):
            pixel = int(nm_to_px(nm) * layout["RING_SCALE"])
            pygame.draw.circle(screen, COLOUR_FIX_RING, (x, y), pixel, 1)
            label = font.render(f"{nm}", True, COLOUR_FIX_TEXT)
            label_offset = int(8 * layout["RING_SCALE"])
            screen.blit(label, (x + pixel + 4, y - label_offset))

        for deg in range(0, 360, RADAR_HEADING_INTERVAL_DEG):
            rad = math.radians(deg)
            length = nm_to_px(RADAR_LINE_RANGE_NM) * layout["RING_SCALE"]
            dx = math.sin(rad) * length
            dy = -math.cos(rad) * length
            pygame.draw.line(screen, (60, 60, 120), (x, y), (x + dx, y + dy))

        pygame.draw.circle(screen, COLOUR_FIX_CENTER_OUTER, (x, y), int(5 * scale))
        pygame.draw.circle(screen, COLOUR_FIX_CENTER_INNER, (x, y), int(2 * scale))
        name_txt = font.render(name, True, COLOUR_FIX_LABEL)
        screen.blit(name_txt, (x + int(10 * scale), y - int(10 * scale)))

    scale = layout["RING_SCALE"]
    for radius in range(RADAR_RING_SPACING, RADAR_RING_MAX_RADIUS, RADAR_RING_SPACING):
        pygame.draw.circle(screen, COLOUR_RADAR_GRID, RADAR_CENTER, int(radius * scale), 1)

    pygame.draw.line(screen, COLOUR_RADAR_GRID,
                     (radar_center[0], radar_rect.top), (radar_center[0], radar_rect.bottom), 1)
    pygame.draw.line(screen, COLOUR_RADAR_GRID,
                     (radar_rect.left, radar_center[1]), (radar_rect.right, radar_center[1]), 1)

    for plane in planes:
        draw_aircraft(screen, font, plane, active=(plane.callsign == active_cs))

    cy = radar_rect.top + 5
    for a, b, lat, vert in conflicts:
        draw_conflict_indicator(a, b, lat, vert, screen, font, radar_rect, cy)
        cy += 18

    pygame.draw.rect(screen, COLOUR_SIDEBAR_BG, sidebar_rect)
    pygame.draw.line(screen, COLOUR_SIDEBAR_BORDER,
                     (sidebar_rect.left, sidebar_rect.top),
                     (sidebar_rect.left, sidebar_rect.bottom), 1)

    display_plane = selected_plane or next((p for p in planes if p.callsign == active_cs), None)

    hover_timestamp = None
    hover_pos = (0, 0)
    mx, my = pygame.mouse.get_pos()

    if display_plane:
        cs = display_plane.callsign
        x0 = sidebar_rect.x + 10
        y0 = sidebar_rect.y + 10

        screen.blit(font.render(f"ACTIVE: {cs}", True, COLOUR_MSG_TITLE), (x0, y0))
        y = y0 + 28

        log = radio_log.get(cs, []) if radio_log else []
        if not log:
            screen.blit(font.render("(no messages yet)", True, COLOUR_MSG_PLACEHOLDER), (x0, y))
        else:
            max_lines = max(5, (sidebar_rect.height - 60) // 18)
            start = max(0, len(log) - max_lines - radio_scroll)
            end = max(0, len(log) - radio_scroll)
            subset = log[start:end]

            for line in subset:
                if isinstance(line, dict):
                    msg = line.get("text", "")
                    ts = line.get("timestamp")
                else:
                    msg = line
                    ts = None

                color = COLOUR_MSG_CTRL if msg.startswith("CTRL") else COLOUR_MSG_TEXT

                for wrapped in wrap_text(msg, font, sidebar_rect.width - 20):
                    if y > sidebar_rect.bottom - 20:
                        break

                    text_surface = font.render(wrapped, True, color)
                    text_rect = text_surface.get_rect(x=x0, y=y)
                    screen.blit(text_surface, text_rect)

                    if text_rect.collidepoint(mx, my) and ts:
                        hover_timestamp = ts
                        hover_pos = (mx, my)

                    y += 18

            if len(log) > max_lines:
                total = len(log) - max_lines
                bar_area_h = sidebar_rect.height - 80
                bar_h = max(20, int(bar_area_h * (max_lines / len(log))))
                bar_y = int(sidebar_rect.y + 40 + (radio_scroll / max(total, 1)) * (bar_area_h - bar_h))
                pygame.draw.rect(screen, COLOUR_MSG_SCROLLBAR,
                                 (sidebar_rect.right - 10, bar_y, 6, bar_h))
    else:
        msg = "Click a plane to view log"
        max_width = sidebar_rect.width - 20
        msg_font = font
        while msg_font.size(msg)[0] > max_width and msg_font.get_height() > 10:
            new_size = int(msg_font.get_height() * 0.9)
            msg_font = pygame.font.SysFont(DEFAULT_FONT, new_size)

        lines = wrap_text(msg, msg_font, max_width)
        y = sidebar_rect.y + 10
        for line in lines:
            txt = msg_font.render(line, True, COLOUR_MSG_HINT)
            screen.blit(txt, (sidebar_rect.x + 10, y))
            y += msg_font.get_height() + 2

    if hover_timestamp:
        tooltip_font = pygame.font.SysFont(DEFAULT_FONT, max(12, int(layout["FONT_SIZE_SIDEBAR"] * 0.9)))
        tooltip_text = tooltip_font.render(hover_timestamp, True, (255, 255, 255))
        pad = 6
        bg_rect = pygame.Rect(
            hover_pos[0] + 14,
            hover_pos[1] + 14,
            tooltip_text.get_width() + pad * 2,
            tooltip_text.get_height() + pad * 2
        )

        if bg_rect.right > window_w - 10:
            bg_rect.x = window_w - bg_rect.width - 10
        if bg_rect.bottom > window_h - 10:
            bg_rect.y = window_h - bg_rect.height - 10

        pygame.draw.rect(screen, (30, 30, 40), bg_rect, border_radius=4)
        pygame.draw.rect(screen, (100, 255, 100), bg_rect, 1, border_radius=4)
        screen.blit(tooltip_text, (bg_rect.x + pad, bg_rect.y + pad))

def hit_test_aircraft(mouse_pos, planes, layout):
    """Detect which aircraft (if any) the mouse clicked on."""
    mx, my = mouse_pos
    for plane in planes:
        px, py = scale_position(plane.x, plane.y, layout)
        hit_radius = max(6, int(10 * layout["RING_SCALE"]))  # same as left-click
        if (px - mx) ** 2 + (py - my) ** 2 <= hit_radius ** 2:
            return plane
    return None

def draw_context_menu(screen, font, x, y):
    """Simple right-click context menu."""
    options = ["Open Performance Profile", "Set Flaps …", "Toggle Gear"]
    w, h = 240, 25 * len(options)
    rect = pygame.Rect(x, y, w, h)
    pygame.draw.rect(screen, (30, 30, 40), rect, border_radius=6)
    pygame.draw.rect(screen, (120, 120, 150), rect, 1, border_radius=6)
    for i, text in enumerate(options):
        txt = font.render(text, True, (255, 255, 255))
        screen.blit(txt, (x + 10, y + 5 + i * 25))
    return rect, options

def draw_aircraft_profile_window(screen, font, planes_or_snapshot, *_):
    """Detached window showing live performance data."""
    snap = planes_or_snapshot
    width, height = screen.get_size()
    screen.fill((0, 0, 25))
    if not snap:
        return
    if "altitude_history" in snap:
        pts = snap["altitude_history"]
        if len(pts) >= 2:
            t0 = pts[0][0]
            scale_x = width / max(1.0, pts[-1][0] - t0)
            min_alt = min(a for _, a in pts)
            max_alt = max(a for _, a in pts)
            scale_y = (height - 120) / max(1.0, max_alt - min_alt)
            graph_pts = [
                (int((t - t0) * scale_x), int(height - 60 - (a - min_alt) * scale_y))
                for t, a in pts
            ]
            if len(graph_pts) >= 2:
                pygame.draw.lines(screen, (0, 255, 0), False, graph_pts, 2)

    lines = [
        f"Model: {snap.get('icao', 'UNKNOWN')}",
        f"Weight: {snap.get('weight_kg', 0):,.0f} kg",
        f"Fuel: {snap.get('fuel_kg', 0):,.0f}/{snap.get('fuel_capacity_kg', 0):,.0f} kg",
        f"Thrust: {snap.get('thrust_pct', 0):.1f} %",
        f"Flaps: {snap.get('flap_state', 0)}",
        f"Gear: {'Down' if snap.get('gear_down') else 'Up'}",
        f"Alt: {snap.get('alt', 0):.0f} ft",
        f"Spd: {snap.get('spd', 0):.0f} kt",
    ]
    for i, txt in enumerate(lines):
        surf = font.render(txt, True, (255, 255, 255))
        screen.blit(surf, (10, 10 + i * 20))