import os
import sys
import time
import psutil
import pygame
import traceback
from collections import defaultdict
from typing import Optional

from update_checker import check_for_update
from atc.ai.controller import AIController
from atc.objects.runway_v2 import all_runways
from atc.objects.aircraft_v2 import spawn_random_plane
from atc.radar import draw_radar, draw_performance_menu, draw_flight_progress_log
from atc.utils import check_conflicts, calculate_layout, get_current_version, ensure_pygame_ready
from atc.command_parser import CommandParser
from atc.ui.window_manager import open_detached_window, close_all_windows, update_shared_state, show_modal, draw_help_window
from constants import (
    WIDTH, HEIGHT, FPS, SIM_SPEED, ERROR_LOG_FILE,
    INITIAL_PLANE_COUNT, DEFAULT_FONT, CURSOR_BLINK_SPEED,
    NAME_MAIN_WINDOW, NAME_FLIGHT_LOG, COLOUR_BTN_TEXT,
    COLOUR_BG, COLOUR_CONSOLE_BG, COLOUR_CONSOLE_TEXT,
    COLOUR_ERROR_BG, COLOUR_ERROR_HEADER, COLOUR_ERROR_TEXT,
    AI_TRAFFIC, AI_SPAWN_INTERVAL_S, INITIAL_PLANE_COUNT,
    MODAL_WIDTH, MODAL_HEIGHT, COLOUR_MODAL_BG, COLOUR_MODAL_CARD,
    COLOUR_MODAL_TEXT, COLOUR_MODAL_SUB, COLOUR_BTN_BG,
    COLOUR_BTN_BG_HOVER
)


parser = CommandParser()
VERSION = get_current_version()
fatal_error = None
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

def handle_exception(exc_type, exc_value, exc_traceback):
    """Log uncaught exceptions and freeze the sim gracefully."""
    global fatal_error

    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    entry = f"[{timestamp}]\n{error_text}\n{'-' * 60}\n"

    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)

    fatal_error = entry
    print("⚠️ Fatal error logged — see error_log.txt")


sys.excepthook = handle_exception

def handle_keyboard_input(event, state):
    """Process all keyboard input events."""
    key = event.key

    # --- Command entered ---
    if key == pygame.K_RETURN and state["input_str"].strip():
        state["messages"].append("> " + state["input_str"])
        results = parser.parse(state["input_str"], state["planes"])

        if state["input_str"].strip().upper() == "HELP":
            state["show_help"] = not state["show_help"]
            state["input_str"] = ""
            state["cursor_pos"] = 0
            return

        if isinstance(results, list):
            segments = [seg.strip() for seg in state["input_str"].split("|") if seg.strip()]
            for res in results:
                cs, ctrl_msg, ack_msg = res["callsign"], res["ctrl_msg"], res["ack_msg"]
                state["messages"].append(ctrl_msg)
                cs_segment = next((seg for seg in segments if seg.startswith(cs)), state["input_str"])
                state["radio_log"][cs].append(f"CTRL: {cs_segment}")
                state["radio_log"][cs].append(f"{cs}: {ack_msg}")

        state["input_str"] = ""
        state["cursor_pos"] = 0

    # --- Editing ---
    elif key == pygame.K_BACKSPACE and state["cursor_pos"] > 0:
        state["input_str"] = state["input_str"][:state["cursor_pos"] - 1] + state["input_str"][state["cursor_pos"]:]
        state["cursor_pos"] -= 1
    elif key == pygame.K_DELETE and state["cursor_pos"] < len(state["input_str"]):
        state["input_str"] = state["input_str"][:state["cursor_pos"]] + state["input_str"][state["cursor_pos"] + 1:]
    elif key == pygame.K_LEFT:
        state["cursor_pos"] = max(0, state["cursor_pos"] - 1)
    elif key == pygame.K_RIGHT:
        state["cursor_pos"] = min(len(state["input_str"]), state["cursor_pos"] + 1)
    elif key == pygame.K_F1:
        state["show_help"] = not state["show_help"]
    elif key == pygame.K_F3:
        state["show_perf"] = not state["show_perf"]
    elif key == pygame.K_F4:
        state["show_flight_log"] = not state["show_flight_log"]
    elif key == pygame.K_F9:
        state["show_error_log"] = not state["show_error_log"]
    elif event.unicode.isprintable():
        state["input_str"] = (
            state["input_str"][:state["cursor_pos"]]
            + event.unicode.upper()
            + state["input_str"][state["cursor_pos"]:]
        )
        state["cursor_pos"] += 1

def handle_update_modal_event(event: pygame.event.Event, state: dict):
    """Consume events while the update modal is visible."""
    if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
        state["show_update_modal"] = False
        return True  # consumed

    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        btn: Optional[pygame.Rect] = state.get("modal_ok_rect")
        if btn and btn.collidepoint(event.pos):
            state["show_update_modal"] = False
            return True  # consumed
    return False


def handle_mouse_input(event, state, layout, screen, font):
    """Process all mouse input events."""
    mx, my = event.pos

    # Expand Flight Progress Log
    if state["show_flight_log"]:
        rects = draw_flight_progress_log(screen, font, state["planes"], layout)
        expand_icon = rects.get("expand_icon") if rects else None
        if expand_icon and expand_icon.collidepoint(event.pos):
            state["show_flight_log"] = False
            return

    # Left click — select aircraft
    if event.button == 1:
        for p in state["planes"]:
            if (p.x - mx) ** 2 + (p.y - my) ** 2 < 10 ** 2:
                state["selected_plane"] = p
                state["active_cs"] = p.callsign
                state["input_str"] = f"{p.callsign} "
                state["cursor_pos"] = len(state["input_str"])
                state["radio_scroll"] = 0
                break
        else:
            state["selected_plane"] = None
            state["active_cs"] = None
            state["input_str"] = ""
            state["cursor_pos"] = 0

    # Scroll log
    elif event.button == 4:
        state["radio_scroll"] = max(0, state["radio_scroll"] - 1)
    elif event.button == 5:
        state["radio_scroll"] += 1


def update_simulation(state, dt):
    """Update aircraft and detect conflicts."""
    try:
        for plane in state["planes"]:
            plane.update(dt)
    except Exception:
        handle_exception(*sys.exc_info())

    state["conflicts"] = check_conflicts(state["planes"])

    # Sync with detached windows
    update_shared_state("Flight Progress Log", [
        {"callsign": p.callsign, "alt": p.alt, "spd": p.spd, "hdg": p.hdg, "state": p.state}
        for p in state["planes"]
    ])

    update_shared_state("Performance", {
        "fps": int(pygame.time.Clock().get_fps()),
        "sim_speed": SIM_SPEED,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "used_mem_mb": psutil.virtual_memory().used / (1024 ** 2),
        "total_mem_mb": psutil.virtual_memory().total / (1024 ** 2),
        "plane_count": len(state["planes"]),
        "runway_count": len(state["runways"]),
        "occupied": ', '.join(r.name for r in state["runways"] if r.status == 'OCCUPIED') or 'None',
        "last_update": time.strftime("%H:%M:%S"),
    })


def render_console(screen, font, state, layout):
    """Draw command console at bottom of screen."""
    console_height = int(layout["FONT_SIZE"] * 2.2)
    bottom_y = HEIGHT - console_height + int(layout["FONT_SIZE"] * 0.5)
    prompt_x = int(layout["FONT_SIZE"] * 0.5)

    pygame.draw.rect(screen, COLOUR_CONSOLE_BG, (0, HEIGHT - console_height, WIDTH, console_height))
    txt = font.render(f"> {state['input_str']}", True, COLOUR_CONSOLE_TEXT)
    screen.blit(txt, (prompt_x, bottom_y))

    if state["cursor_visible"]:
        cursor_width = font.render(f"> {state['input_str'][:state['cursor_pos']]}", True, COLOUR_CONSOLE_TEXT).get_width()
        pygame.draw.rect(screen, COLOUR_CONSOLE_TEXT,
                         (prompt_x + cursor_width, bottom_y - 2, 2, font.get_height()))


def render_error_overlay(screen, font, error_text):
    """Display fatal error log overlay."""
    surf = pygame.Surface((WIDTH - 100, HEIGHT - 100), pygame.SRCALPHA)
    surf.fill(COLOUR_ERROR_BG)
    y = 20
    for line in str(error_text).splitlines()[-30:]:
        surf.blit(font.render(line, True, COLOUR_ERROR_TEXT), (20, y))
        y += 18
    screen.blit(surf, (50, 50))
    screen.blit(font.render("FATAL ERROR — PRESS F9 TO HIDE", True, COLOUR_ERROR_HEADER), (60, 60))

def main():
    ensure_pygame_ready()
    global fatal_error
    
    ai = AIController()
    ai_enabled = AI_TRAFFIC
    ai_spawn_timer = 0.0
    
    pygame.init()

    has_update, remote_version = check_for_update(VERSION)
    if has_update and remote_version:
        print(f"Update available: {remote_version} (local {VERSION})")
        pygame.display.set_caption(f"{NAME_MAIN_WINDOW} {VERSION} - Update EXE to {remote_version}")
        update_info = { "remote": remote_version, "local": VERSION }
        show_modal("Update Available", f"A new version ({remote_version}) is available.\nLet a developer know to update this machine.")
    else:
        print("PyATC up-to-date!")
        pygame.display.set_caption(f"{NAME_MAIN_WINDOW} {VERSION}")
        update_info = None

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    clock = pygame.time.Clock()

    state = {
        "planes": [spawn_random_plane(i) for i in range(1, INITIAL_PLANE_COUNT + 1)],
        "runways": all_runways(),
        "radio_log": defaultdict(list),
        "messages": [],
        "selected_plane": None,
        "active_cs": None,
        "radio_scroll": 0,
        "input_str": "",
        "cursor_pos": 0,
        "cursor_visible": True,
        "cursor_timer": 0,
        "show_help": False,
        "show_perf": False,
        "show_flight_log": False,
        "show_error_log": False,
        "conflicts": [],
        "show_update_modal": bool(update_info),
        "update_info": update_info,
        "modal_ok_rect": None, 
    }

    running = True
    while running:
        dt = 0 if fatal_error else (clock.tick(FPS) / 1000.0) * SIM_SPEED
        
        if ai_enabled:
            ai_spawn_timer += dt
            if ai_spawn_timer >= AI_SPAWN_INTERVAL_S:
                ai_spawn_timer = 0.0
                p = spawn_random_plane(len(state["planes"]) + 1)
                p.ai_controlled = True
                state["planes"].append(p)
            
            ai.update(state["planes"], state["runways"], dt)

        # Cursor blink timing
        state["cursor_timer"] += dt
        if state["cursor_timer"] >= CURSOR_BLINK_SPEED:
            state["cursor_visible"] = not state["cursor_visible"]
            state["cursor_timer"] = 0

        layout = calculate_layout(WIDTH, HEIGHT)
        if not pygame.font.get_init():
            pygame.font.init()
        font = pygame.font.SysFont(DEFAULT_FONT, layout["FONT_SIZE"])

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                close_all_windows()
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                handle_mouse_input(event, state, layout, screen, font)
            elif event.type == pygame.KEYDOWN:
                handle_keyboard_input(event, state)

            if state["show_update_modal"]:
                if handle_update_modal_event(event, state):
                    continue
                
        update_simulation(state, dt)

        try:
            draw_radar(
                screen, state["planes"], font, state["messages"], state["conflicts"],
                radio_log=state["radio_log"], active_cs=state["active_cs"],
                selected_plane=state["selected_plane"], radio_scroll=state["radio_scroll"],
                runways=state["runways"]
            )
        except pygame.error:
            break

        if state["show_error_log"] and fatal_error:
            render_error_overlay(screen, font, fatal_error)
        if state["show_help"]:
            open_detached_window("Help", draw_help_window)
        if state["show_perf"]:
            open_detached_window("Performance", draw_performance_menu, state["planes"], state["runways"], SIM_SPEED)
        if state["show_flight_log"]:
            open_detached_window(NAME_FLIGHT_LOG, draw_flight_progress_log, state["planes"], layout)

        render_console(screen, font, state, layout)

        pygame.display.flip()

    pygame.quit()
    close_all_windows()
    sys.exit()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # required on Windows
    main()