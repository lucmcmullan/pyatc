import pygame
import multiprocessing
from constants import (
    WIDTH, HEIGHT,
    HELP_TEXT,
    WINDOW_HELP, WINDOW_ERROR,
    WINDOW_FLIGHT_PROGRESS, WINDOW_PERFORMANCE
)
from atc.utils import wrap_text, ensure_pygame_ready, calculate_layout
from multiprocessing.managers import SyncManager, DictProxy
from multiprocessing.process import BaseProcess
from typing import Any, Dict, Optional, Callable

_manager: Optional[SyncManager] = None
_shared_state: Optional[DictProxy] = None
_active_windows: dict[str, BaseProcess] = {}

# ==============================================================
# 🧭 HELP WINDOW DRAW
# ==============================================================
def draw_help_window(screen, font, *_, **__):
    layout = calculate_layout(WIDTH, HEIGHT)
    screen.fill((15, 15, 25))
    x, y = 20, 20
    line_h = int(layout["FONT_SIZE"] * 1.2)
    for line in HELP_TEXT.strip().splitlines():
        if not line:
            y += line_h // 2
            continue
        txt = font.render(line, True, (230, 230, 230))
        screen.blit(txt, (x, y))
        y += line_h


# ==============================================================
# 🪟 MODAL POPUP
# ==============================================================
def _modal_process(title: str, message: str, font_name: str, font_size: int):
    """Run a simple blocking modal window in a separate process.

    This process has its own pygame.display, so it does NOT affect the main sim window.
    """
    pygame.init()

    # Modal size (fixed; independent of main window)
    modal_w, modal_h = 480, 240
    screen = pygame.display.set_mode((modal_w, modal_h))
    pygame.display.set_caption(title)

    clock = pygame.time.Clock()
    font = pygame.font.SysFont(font_name, font_size)

    COLOUR_BG = (30, 30, 40)
    COLOUR_TEXT = (255, 255, 255)
    COLOUR_BTN_BG = (70, 130, 180)
    COLOUR_BTN_BG_HOVER = (90, 150, 200)

    btn_w, btn_h = 100, 40
    btn_x = (modal_w - btn_w) // 2
    btn_y = 180
    btn_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (
                pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE
            ):
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and btn_rect.collidepoint(event.pos):
                running = False

        screen.fill(COLOUR_BG)

        title_text = font.render(title, True, COLOUR_TEXT)
        screen.blit(title_text, (30, 30))

        wrapped = wrap_text(message, font, modal_w - 60)
        y = 70
        for line in wrapped:
            line_surface = font.render(line, True, COLOUR_TEXT)
            screen.blit(line_surface, (30, y))
            y += 25

        mouse = pygame.mouse.get_pos()
        hover = btn_rect.collidepoint(mouse)
        pygame.draw.rect(screen, COLOUR_BTN_BG_HOVER if hover else COLOUR_BTN_BG, btn_rect, border_radius=6)

        ok_text = font.render("OK", True, COLOUR_TEXT)
        screen.blit(
            ok_text,
            (btn_x + (btn_w - ok_text.get_width()) // 2,
             btn_y + (btn_h - ok_text.get_height()) // 2),
        )

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

def show_modal(title: str, message: str, font_name: str = "Consolas", font_size: int = 18):
    """Blocking modal that runs in a separate process without modifying the main window."""
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_modal_process,
        args=(title, message, font_name, font_size),
        daemon=True,
    )
    proc.start()
    #proc.join()

# ==============================================================
# 🔄 MULTIPROCESS MANAGER
# ==============================================================
def _ensure_manager() -> None:
    global _manager, _shared_state
    if _manager is None:
        ctx = multiprocessing.get_context("spawn")
        _manager = ctx.Manager()
        _shared_state = _manager.dict()


def update_shared_state(key: str, data: Any) -> None:
    _ensure_manager()
    assert _shared_state is not None
    _shared_state[key] = data


def get_shared_state(key: str) -> Any:
    _ensure_manager()
    assert _shared_state is not None
    return _shared_state.get(key)


# ==============================================================
# 🪟 OPEN DETACHED WINDOW
# ==============================================================
def open_detached_window(
    title: str,
    draw_func: Callable[..., Any],
    *args: Any,
    **kwargs: Any
) -> None:
    """Create and display a detached Pygame window in a new process."""
    _ensure_manager()
    kwargs.pop("live", None)

    existing = _active_windows.get(title)
    if existing and existing.is_alive():
        return

    ctx = multiprocessing.get_context("spawn")
    assert _shared_state is not None
    proc = ctx.Process(
        target=_window_process,
        args=(title, draw_func, _shared_state, title) + args,
        kwargs=kwargs,
        daemon=True,
    )
    proc.start()
    _active_windows[title] = proc


def close_all_windows() -> None:
    """Safely close all active detached windows."""
    for proc in list(_active_windows.values()):
        if proc.is_alive():
            proc.terminate()
    _active_windows.clear()


# ==============================================================
# 🧩 DETACHED WINDOW LOOP
# ==============================================================
def _window_process(
    title: str,
    draw_func: Callable[..., None],
    shared_state_proxy: Dict[str, Any],
    shared_key: str,
    *args: Any,
    **kwargs: Any
) -> None:
    pygame.init()
    info = pygame.display.Info()
    screen_w, screen_h = info.current_w, info.current_h

    # --- Dynamic scaling per window type ---
    if title == WINDOW_FLIGHT_PROGRESS:
        window_size = (int(screen_w * 0.35), int(screen_h * 0.55))
    elif title == WINDOW_PERFORMANCE:
        window_size = (int(screen_w * 0.3), int(screen_h * 0.35))
    elif title == WINDOW_HELP:
        window_size = (int(screen_w * 0.45), int(screen_h * 0.6))
    elif title == WINDOW_ERROR:
        window_size = (int(screen_w * 0.4), int(screen_h * 0.7))
    else:
        window_size = (int(screen_w * 0.4), int(screen_h * 0.5))

    # Center the window on the screen
    x = (screen_w - window_size[0]) // 2
    y = (screen_h - window_size[1]) // 2
    os_env = pygame.display.get_wm_info()
    pygame.display.set_mode(window_size, pygame.NOFRAME)
    window = pygame.display.set_mode(window_size, 0)
    pygame.display.set_caption(f"PyATC - {title}")

    font = pygame.font.SysFont("Consolas", 16)
    clock = pygame.time.Clock()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        window.fill((0, 0, 20))
        snapshot = shared_state_proxy.get(shared_key)
        if snapshot is not None:
            draw_func(screen=window, font=font, planes_or_snapshot=snapshot)
        else:
            msg = font.render("Waiting for data sync...", True, (200, 200, 100))
            window.blit(msg, (20, 20))

        pygame.display.flip()
        clock.tick(30)

    pygame.display.quit()