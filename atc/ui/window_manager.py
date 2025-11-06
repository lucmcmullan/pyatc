import pygame
import multiprocessing
from multiprocessing.managers import SyncManager, DictProxy
from multiprocessing.process import BaseProcess
from typing import Any, Dict, Optional, Callable

_manager: Optional[SyncManager] = None
_shared_state: Optional[DictProxy] = None
_active_windows: dict[str, BaseProcess] = {}

def _ensure_manager() -> None:
    """Ensure a multiprocessing manager and shared dictionary exist."""
    global _manager, _shared_state
    if _manager is None:
        ctx = multiprocessing.get_context("spawn")
        _manager = ctx.Manager()
        _shared_state = _manager.dict()


def update_shared_state(key: str, data: Any) -> None:
    """Push a new snapshot of live data to the shared state dictionary."""
    _ensure_manager()
    assert _shared_state is not None, "Shared state not initialized"
    _shared_state[key] = data


def get_shared_state(key: str) -> Any:
    """Retrieve shared state data for a specific key."""
    _ensure_manager()
    assert _shared_state is not None, "Shared state not initialized"
    return _shared_state.get(key)

def open_detached_window(
    title: str,
    draw_func: Callable[..., Any],
    *args: Any,
    **kwargs: Any
) -> None:
    """
    Create and display a new detached Pygame window in a separate process.

    Parameters:
        title: Window title (used as key for process tracking)
        draw_func: Function responsible for drawing window content
        *args, **kwargs: Passed to draw_func
    """
    _ensure_manager()
    kwargs.pop("live", None)

    existing = _active_windows.get(title)
    if existing and existing.is_alive():
        return

    ctx = multiprocessing.get_context("spawn")
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

def _window_process(
    title: str,
    draw_func: Callable[..., None],
    shared_state_proxy: Dict[str, Any],
    shared_key: str,
    *args: Any,
    **kwargs: Any
) -> None:
    """
    Run a Pygame window in a separate process that continuously
    renders the latest shared-state snapshot.
    """
    pygame.init()
    try:
        # Setup
        window = pygame.display.set_mode((550, 650), pygame.RESIZABLE)
        pygame.display.set_caption(f"PyATC - {title}")
        font = pygame.font.SysFont("Consolas", 16)
        clock = pygame.time.Clock()

        kwargs.pop("live", None)

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            window.fill((0, 0, 20))

            snapshot = shared_state_proxy.get(shared_key)
            if snapshot is not None:
                clean_kwargs = {**kwargs}
                clean_kwargs.pop("live", None)
                draw_func(screen=window, font=font, planes_or_snapshot=snapshot, **clean_kwargs, live=True)
            else:
                msg = font.render("Waiting for data sync...", True, (200, 200, 100))
                window.blit(msg, (20, 20))

            pygame.display.flip()
            clock.tick(30)

    finally:
        pygame.quit()