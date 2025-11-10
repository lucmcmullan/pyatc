import os
import sys
import time
import psutil
import pygame
import datetime
import traceback
from collections import defaultdict
from typing import Optional

from update_checker import check_for_update
from atc.ai.voice import speak
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
    WINDOW_MAIN, FUNCTION_KEYS, WINDOW_PERFORMANCE, HELP_TEXT,
    COLOUR_CONSOLE_BG, COLOUR_CONSOLE_TEXT, INITIAL_PLANE_COUNT,
    COLOUR_ERROR_BG, COLOUR_ERROR_HEADER, COLOUR_ERROR_TEXT,
    AI_TRAFFIC, AI_SPAWN_INTERVAL_S, WINDOW_HELP, WINDOW_ERROR,
    WINDOW_FLIGHT_PROGRESS, RESPONSE_VOICE
)


parser = CommandParser()
VERSION = get_current_version()
fatal_error = None

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

clock = pygame.time.Clock()

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
    info = pygame.display.Info()

    layout = calculate_layout(info.current_w, info.current_h)

    """Process all keyboard input events."""
    key = event.key

    # --- Command entered ---
    if key == pygame.K_RETURN and state["input_str"].strip():
        state["messages"].append("> " + state["input_str"])
        results = parser.parse(state["input_str"], state["planes"])

        if state["input_str"].strip().upper() == "HELP":
            open_detached_window("Help", draw_help_window)
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
                speak(ack_msg)

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
    elif key == FUNCTION_KEYS["help"]:
        open_detached_window(WINDOW_HELP, draw_help_window)
    elif key == FUNCTION_KEYS["performance"]:
        open_detached_window(WINDOW_PERFORMANCE, draw_performance_menu, state["planes"], state["runways"], SIM_SPEED)
    elif key == FUNCTION_KEYS["flight_progress"]:
        open_detached_window(WINDOW_FLIGHT_PROGRESS, draw_flight_progress_log, state["planes"], layout)
    elif key == FUNCTION_KEYS["ai_mode"]:
        state["ai_enabled"] = not state["ai_enabled"]
        show_modal("AI Mode", f"AI Mode {'Enabled' if state['ai_enabled'] else 'Disabled'}")
    elif key == FUNCTION_KEYS["voice_response"]:
        state["voice_enabled"] = not state["voice_enabled"]
        show_modal("Voice Response", f"Voice Response {'Enabled' if state['voice_enabled'] else 'Disabled'}")

    elif key == FUNCTION_KEYS["errors"]:
        if fatal_error:
            show_modal(WINDOW_ERROR, fatal_error)
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

    update_shared_state(WINDOW_FLIGHT_PROGRESS, [
        {"callsign": p.callsign, "alt": p.alt, "spd": p.spd, "hdg": p.hdg, "state": p.state}
        for p in state["planes"]
    ])

    update_shared_state(WINDOW_PERFORMANCE, {
        "fps": int(state.get("fps_avg", 0)),
        "sim_speed": SIM_SPEED,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "used_mem_mb": psutil.virtual_memory().used / (1024 ** 2),
        "total_mem_mb": psutil.virtual_memory().total / (1024 ** 2),
        "plane_count": len(state["planes"]),
        "runway_count": len(state["runways"]),
        "occupied": ', '.join(r.name for r in state["runways"] if r.status == 'OCCUPIED') or 'None',
    })

    update_shared_state(WINDOW_HELP, {"title": f"PyATC {VERSION} Help Reference", "text": HELP_TEXT})
    
def render_console(screen, font, state, layout):
    """Draw command console anchored to bottom, stretched to width."""
    rect = layout["CONSOLE_RECT"]

    pygame.draw.rect(screen, COLOUR_CONSOLE_BG, rect)

    prompt = f"> {state['input_str']}"
    txt = font.render(prompt, True, COLOUR_CONSOLE_TEXT)
    text_y = rect.y + (rect.height - txt.get_height()) // 2
    screen.blit(txt, (rect.x + 10, text_y))

    if state["cursor_visible"]:
        before = f"> {state['input_str'][:state['cursor_pos']]}"
        cursor_x = rect.x + 10 + font.size(before)[0]
        cursor_y = text_y
        pygame.draw.rect(
            screen,
            COLOUR_CONSOLE_TEXT,
            (cursor_x, cursor_y, 2, txt.get_height() - 2),
        )

def render_clock(screen):
    import datetime
    from constants import DEFAULT_FONT

    # Get dynamic screen size (not constants)
    window_w, window_h = screen.get_size()

    # Scale font size relative to window height (2.5% baseline)
    scaled_size = max(12, int(window_h * 0.025))
    font = pygame.font.SysFont(DEFAULT_FONT, scaled_size)

    # Render clock text
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
    text = font.render(now, True, (0, 255, 0))

    # Padding scales slightly with height
    padding = max(8, int(window_h * 0.015))

    # Bottom-right positioning
    x = window_w - text.get_width() - padding
    y = window_h - text.get_height() - padding

    screen.blit(text, (x, y))

def main():
    ensure_pygame_ready()
    global fatal_error
    
    ai = AIController()
    ai_spawn_timer = 0.0
    
    pygame.init()

    info = pygame.display.Info()
    screen_w, screen_h = info.current_w, info.current_h
    PADDING = 120
    WIDTH = max(800, screen_w - PADDING)
    HEIGHT = max(600, screen_h - PADDING)

    has_update, remote_version = check_for_update(VERSION)
    if has_update and remote_version:
        print(f"Update available: {remote_version} (local {VERSION})")
        pygame.display.set_caption(f"{WINDOW_MAIN} {VERSION} - Update EXE to {remote_version}")
        update_info = {"remote": remote_version, "local": VERSION}
        show_modal("Update Available", f"A new version ({remote_version}) is available.\nLet a developer know to update this machine.")
    else:
        print("PyATC up-to-date!")
        pygame.display.set_caption(f"{WINDOW_MAIN} {VERSION}")
        update_info = None

    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
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
        "conflicts": [],
        "show_update_modal": bool(update_info),
        "update_info": update_info,
        "modal_ok_rect": None, 
        "fps_avg": 0.0,
        "ai_enabled": AI_TRAFFIC,
        "voice_enabled": RESPONSE_VOICE,
    }

    running = True
    while running:
        dt = 0 if fatal_error else (clock.tick(FPS) / 1000.0) * SIM_SPEED

        current_fps = clock.get_fps()
        state["fps_avg"] = (state.get("fps_avg", current_fps) * 0.9) + (current_fps * 0.1)

        if state.get("ai_enabled"):
            ai.update(state["planes"], state["runways"], dt)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                close_all_windows()
                running = False

            elif event.type == pygame.VIDEORESIZE:
                # Only update screen when user manually resizes
                WIDTH, HEIGHT = event.w, event.h
                screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                handle_mouse_input(event, state, calculate_layout(WIDTH, HEIGHT), screen, font)
            elif event.type == pygame.KEYDOWN:
                handle_keyboard_input(event, state)

            if state["show_update_modal"]:
                if handle_update_modal_event(event, state):
                    continue

        # --- Update simulation ---
        update_simulation(state, dt)

        # --- Draw ---
        layout = calculate_layout(WIDTH, HEIGHT)
        if not pygame.font.get_init():
            pygame.font.init()
        font = pygame.font.SysFont(DEFAULT_FONT, layout["FONT_SIZE"])

        draw_radar(
            screen, state["planes"], font, state["messages"], state["conflicts"],
            radio_log=state["radio_log"], active_cs=state["active_cs"],
            selected_plane=state["selected_plane"], radio_scroll=state["radio_scroll"],
            runways=state["runways"]
        )
        render_console(screen, font, state, layout)
        render_clock(screen)

        pygame.display.flip()

    pygame.quit()
    close_all_windows()
    sys.exit()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # required on Windows
    main()