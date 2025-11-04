import math, pygame
import psutil
from atc.utils import heading_to_vec, load_fixes, nm_to_px, wrap_text, calculate_layout
from constants import WIDTH, HEIGHT

def draw_aircraft(screen, font, plane, active=False):
    colour = (0, 255, 0) if not active else (255, 255, 0)

    size = 8
    rect = pygame.Surface((size, size), pygame.SRCALPHA)
    rect.fill(colour)

    rotated = pygame.transform.rotate(rect, -plane.hdg)
    rect_rect = rotated.get_rect(center=(plane.x, plane.y))
    screen.blit(rotated, rect_rect.topleft)

    dx, dy = heading_to_vec(plane.hdg)
    line_len = 25
    end_x = plane.x + dx * line_len
    end_y = plane.y + dy * line_len
    pygame.draw.line(screen, colour, (plane.x, plane.y), (end_x, end_y), 2)

    tag_callsign = f"{plane.callsign}"
    tag_info = f"{int(plane.alt)} {int(plane.spd)} {int(plane.hdg)}"

    text_callsign = font.render(tag_callsign, True, colour)
    text_info = font.render(tag_info, True, colour)

    screen.blit(text_callsign, (plane.x + 10, plane.y - 20))
    screen.blit(text_info, (plane.x + 10, plane.y - 5))

def draw_performance_menu(screen, font, clock, planes, runways, sim_speed):
    fps = int(clock.get_fps())
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    used_mem_mb = mem.used / (1024 ** 2)
    total_mem_mb = mem.total / (1024 ** 2)

    aircraft_count = len(planes)
    runway_count = len(runways)
    occupied = [r.name for r in runways if r.status == "OCCUPIED"]
    queued_commands = sum(len(p.command_queue) for p in planes)

    lines = [
        "PERFORMANCE PROFILE"
        f"FPS: {fps}",
        f"Simulation speed: {sim_speed:.1f}x",
        f"CPU usage: {cpu_percent:.1f}%",
        f"Memory: {used_mem_mb:.0f} / {total_mem_mb:.0f} MB",
        f"Aircraft active: {aircraft_count}",
        f"Runways active: {runway_count}",
        f"Runways occupied: {', '.join(occupied) if occupied else 'None'}",
        f"Total queued commands: {queued_commands}",
    ]

    width = 360
    height = len(lines) * 22 + 20
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    surf.fill((10, 10, 10, 210))

    y = 10
    for line in lines:
        text = font.render(line, True, (255, 255, 180))
        surf.blit(text, (10, y))
        y += 22

    screen.blit(surf, (10, 10))

def draw_radar(screen, planes, font, messages, conflicts,
               radio_log=None, active_cs=None, selected_plane=None, radio_scroll=0, 
               runways=None):

    layout = calculate_layout(WIDTH, HEIGHT)
    RADAR_WIDTH = layout["RADAR_WIDTH"]
    RADAR_CENTER = layout["RADAR_CENTER"]
    SIDEBAR_WIDTH = layout["SIDEBAR_WIDTH"]
    SIDEBAR_OFFSET = layout["SIDEBAR_OFFSET"]
    sidebar_x = RADAR_WIDTH - SIDEBAR_OFFSET
    BOTTOM_MARGIN = layout["BOTTOM_MARGIN"]
    
    screen.fill((0, 0, 20))
    
    if runways:
        for rw in runways:
            rw.draw(screen, font)

    # VOR, fixes
    fixes = load_fixes()
    for name, position in fixes.items():
        x, y = position["x"], position["y"]
        scale = position.get("ring_scale", 1.0)

        # --- Scaled range rings ---
        for nm in range(10, 30, 10):
            pixel = int(nm_to_px(nm) * scale)
            pygame.draw.circle(screen, (50, 50, 100), (x, y), pixel, 1)
            text = font.render(f"{nm}", True, (100, 120, 180))
            screen.blit(text, (x + pixel + 4, y - int(8 * scale)))

        # --- Scaled radial lines ---
        for deg in range(0, 360, 30):
            rad = math.radians(deg)
            dx = math.sin(rad) * nm_to_px(20) * scale
            dy = -math.cos(rad) * nm_to_px(20) * scale
            pygame.draw.line(screen, (60, 60, 120), (x, y), (x + dx, y + dy))

        # --- Scaled fix marker ---
        pygame.draw.circle(screen, (100, 100, 255), (x, y), int(5 * scale))
        pygame.draw.circle(screen, (180, 180, 255), (x, y), int(2 * scale))

        # --- Scaled label ---
        label = font.render(name, True, (180, 180, 255))
        screen.blit(label, (x + int(10 * scale), y - int(10 * scale)))

    # radar grid, circles
    for radius in range(100, 1300, 100):
        pygame.draw.circle(screen, (0, 60, 0), RADAR_CENTER, radius, 1)

    pygame.draw.line(screen, (0, 60, 0), (RADAR_CENTER[0], 0), (RADAR_CENTER[0], HEIGHT), 1)
    pygame.draw.line(screen, (0, 60, 0), (0, RADAR_CENTER[1]), (RADAR_WIDTH, RADAR_CENTER[1]), 1)

    # aircraft
    for plane in planes:
        draw_aircraft(screen, font, plane, active=(plane.callsign == active_cs))

    # conflicts
    y = 5
    for a, b, lat, vert in conflicts:
        msg = f"CONFLICT {a.callsign}-{b.callsign} {lat:.1f}NM {vert:.0f}FT"
        screen.blit(font.render(msg, True, (255, 80, 80)), (5, y))
        y += 18

    # bottom log panel
    #y = HEIGHT - BOTTOM_MARGIN
    #for m in messages[-5:]:
    #    screen.blit(font.render(m, True, (255, 255, 255)), (5, y))
    #    y += 18

    # radio log panel
    pygame.draw.rect(screen, (10, 10, 10), (sidebar_x, 0, SIDEBAR_WIDTH, HEIGHT))
    pygame.draw.line(screen, (60, 60, 60), (sidebar_x, 0), (sidebar_x, HEIGHT), 1)

    display_plane = selected_plane
    if not display_plane and active_cs:
        for plane in planes:
            if plane.callsign == active_cs:
                display_plane = plane
                break

    if display_plane:
        cs = display_plane.callsign
        title = f"ACTIVE: {cs}"
        screen.blit(font.render(title, True, (255, 255, 0)), (sidebar_x + 10, 10))

        log = radio_log.get(cs, []) if radio_log else []
        visible_lines = 30
        y = 40

        if not log:
            screen.blit(font.render("(no messages yet)", True, (120, 120, 120)),
                        (sidebar_x + 10, y))
        else:
            start = max(0, len(log) - visible_lines - radio_scroll)
            end = max(0, len(log) - radio_scroll)
            subset = log[start:end]

            for line in subset:
                color = (150, 150, 255) if line.startswith("CTRL") else (255, 255, 255)
                wrapped_lines = wrap_text(line, font, SIDEBAR_WIDTH - 25)
                for wrapped in wrapped_lines:
                    txt = font.render(wrapped, True, color)
                    screen.blit(txt, (sidebar_x + 10, y))
                    y += 18

            # scroll bar
            if len(log) > visible_lines:
                total = len(log) - visible_lines
                bar_h = max(20, int(200 * (visible_lines / len(log))))
                bar_y = int(40 + (radio_scroll / total) * (200 - bar_h))
                pygame.draw.rect(screen, (80, 80, 80),
                                 (sidebar_x + SIDEBAR_WIDTH - 15, bar_y, 8, bar_h))
    else:
        screen.blit(font.render("Click a plane to view log", True, (180, 180, 180)),
                    (sidebar_x + 10, 10))