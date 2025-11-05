import pygame
import multiprocessing
from multiprocessing.process import BaseProcess
from multiprocessing.managers import SyncManager
from typing import Any, Dict, Optional

_manager: Optional[SyncManager] = None
_shared_state = None
_active_windows: Dict[str, BaseProcess] = {}

def _ensure_manager():
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
    return _shared_state.get(key, None)

def open_detached_window(title: str, draw_func, *args, **kwargs):
    _ensure_manager()
    kwargs.pop("live", None)

    proc = _active_windows.get(title)
    if proc and proc.is_alive():
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

def close_all_windows():
    for p in list(_active_windows.values()):
        if p.is_alive():
            p.terminate()
    _active_windows.clear()

def _window_process(title: str, draw_func, shared_state_proxy, shared_key: str, *args, **kwargs):
    pygame.init()
    try:
        win = pygame.display.set_mode((550, 650), pygame.RESIZABLE)
        pygame.display.set_caption(f"PyATC - {title}")
        font = pygame.font.SysFont("Consolas", 16)
        clock = pygame.time.Clock()

        if "live" in kwargs:
            del kwargs["live"]

        running = True
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False

            win.fill((0, 0, 20))

            snapshot = shared_state_proxy.get(shared_key, None)
            if snapshot is not None:
                clean_kwargs = dict(kwargs)
                clean_kwargs.pop("live", None)

                draw_func(screen=win, font=font, planes_or_snapshot=snapshot, **clean_kwargs, live=True)
            else:
                txt = font.render("Waiting for data sync...", True, (200, 200, 100))
                win.blit(txt, (20, 20))

            pygame.display.flip()
            clock.tick(30)
    finally:
        pygame.quit()