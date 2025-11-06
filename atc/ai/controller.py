import math
import random
import time
from typing import List

from atc.objects.command import Command
from .quadtree import Quadtree
from atc.utils import load_fixes, get_heading_to_fix, nm_to_px
from constants import (
    WIDTH, HEIGHT, SAFE_LAT_NM,
    AI_DECISION_PERIOD, AI_DECONFLICT_TURN,
    AI_APPROACH_ARM_DIST_NM, AI_ALIGN_ALLOWED_DIFF_DEG,
    AI_LANDING_SPEED
)

class AIController:
    def __init__(self):
        self._fix_names = list(load_fixes().keys()) or []

    def update(self, planes: List, runways: List, dt: float):
        if not planes:
            return
        
        qt = Quadtree(0, 0, WIDTH, HEIGHT, cap=8, max_depth=8)
        for p in planes:
            qt.insert(p.x, p.y, p)
        
        now = time.time()

        for ac in planes:
            if not getattr(ac, "ai_controlled", False):
                continue

            if now < getattr(ac, "_ai_next_decision", 0.0):
                continue

            ac._ai_next_decision = now + AI_DECISION_PERIOD

            nearby = qt.query_radius(ac.x, ac.y, nm_to_px(SAFE_LAT_NM * 0.8))
            nearby = [o for o in nearby if o is not ac]

            if nearby:
                turn = AI_DECONFLICT_TURN * (1 if random.random() < 0.5 else -1)
                new_hdg = int((ac.hdg + turn) % 180)
                ac.command_queue.append(Command("HDG", f"{new_hdg:03d}"))
                continue
            
            target = self._choose_runway_for(ac, runways)
            if target is not None:
                runway, align_hdg = target
                ac.command_queue.extend([
                    Command("HDG", f"{align_hdg:03d}"),
                    Command("SPD", str(AI_LANDING_SPEED)),
                    Command("ALT", "0"),
                    Command("LAND", runway.name)
                ])
                
                continue
            
            if self._fix_names:
                fix = random.choice(self._fix_names)
                ac.command_queue.append(Command("NAV", fix))

    def _choose_runway_for(self, ac, runways):
        if not runways:
            return None
        
        candidates = []
        for rw in runways:
            if not rw.is_available():
                continue
            
            diff = abs(((rw.bearing - ac.hdg) + 540) % 360 - 180)
            if diff <= AI_ALIGN_ALLOWED_DIFF_DEG:
                candidates.append((rw, diff))

        if not candidates:
            return None
        
        candidates.sort(key=lambda t: t[1])
        best_runway = candidates[0][0]

        dx, dy = ac.x - best_runway.x, ac.y - best_runway.y

        dist_px = math.hypot(dx, dy)
        if dist_px <= nm_to_px(AI_APPROACH_ARM_DIST_NM):
            return best_runway, best_runway.bearing
        
        return None