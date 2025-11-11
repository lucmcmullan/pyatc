from __future__ import annotations
import math, time, random
import numpy as np
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from atc.utils import nm_to_px
from constants import SAFE_LAT_NM, SAFE_VERT_FT, HELPER_CONFLICT_THRESHOLD, ML_MODEL_PATH, HELPER_UPDATE_INTERVAL

try:
    from joblib import load
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

def distance_nm(a, b) -> float:
    dx, dy = a.x - b.x, a.y - b.y
    dist_px = math.hypot(dx, dy)
    return dist_px / nm_to_px(1)

def heading_diff(h1: float, h2: float) -> float:
    return abs(((h1 - h2 + 180) % 360) - 180)

def extract_features(a, b) -> list[float]:
    dx, dy = a.x - b.x, a.y - b.y
    dist_nm = distance_nm(a, b)
    vert_ft = abs(a.alt - b.alt)
    spd_diff = abs(a.spd - b.spd)
    hdg_diff = heading_diff(a.hdg, b.hdg)
    return [dist_nm, vert_ft, spd_diff, hdg_diff]

@dataclass
class MLAssistant:
    conflict_model: Optional[object] = None
    last_update: float = 0.0
    predicted_conflicts: list[tuple[str, str, float]] = field(default_factory=list)
    suggestions: list[tuple[str, str]] = field(default_factory=list)
    executor: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=1))

    def __post_init__(self):
        if ML_AVAILABLE:
            try:
                self.conflict_model = load(ML_MODEL_PATH)
                print("[ML] Conflict predictor model loaded successfully.")
            except FileNotFoundError:
                print("[ML] No trained model found — using heuristic mode.")
                self.conflict_model = None
            except Exception as e:
                print(f"[ML] Error loading model: {e}. Falling back to heuristic mode.")
                self.conflict_model = None
        else:
            print("[ML] joblib not available. Using heuristic fallback.")

    def update_async(self, planes: List, runways: List) -> None:
        now = time.time()
        if now - self.last_update < HELPER_UPDATE_INTERVAL:
            return
        self.last_update = now
        self.executor.submit(self._update_predictions, planes, runways)

    def get_conflicts(self) -> List[tuple[str, str, float]]:
        return self.predicted_conflicts
    
    def get_suggestions(self) -> List[tuple[str, str]]:
        return self.suggestions
    
    def _update_predictions(self, planes: List, runways: List) -> None:
        conflicts = self._predict_conflicts(planes)
        suggestions = self._generate_suggestions(conflicts, planes)
        self.predicted_conflicts = conflicts
        self.suggestions = suggestions

    def _predict_conflicts(self, planes: List) -> List[tuple[str, str, float]]:
        results = []
        for index in range(len(planes)):
            for nxt in range(index + 1, len(planes)):
                a, b = planes[index], planes[nxt]
                risk = self._pair_conflict_risk(a, b)
                if risk >= HELPER_CONFLICT_THRESHOLD:
                    results.append((a.callsign, b.callsign, risk))
        return results
    
    def _pair_conflict_risk(self, a, b) -> float:
        if self.conflict_model:
            features = np.array(extract_features(a, b)).reshape(1, -1)
            prob = float(self.conflict_model.predict_proba(features)[0, 1])
            return prob
        
        dist_nm = distance_nm(a, b)
        vert_ft = abs(a.alt - b.alt)
        hdg_delta = heading_diff(a.hdg, b.hdg)
        risk = 0.0

        if dist_nm < SAFE_LAT_NM * 2:
            risk += (SAFE_LAT_NM * 2 - dist_nm) / (SAFE_LAT_NM * 2)
        if vert_ft < SAFE_VERT_FT * 3:
            risk += (SAFE_VERT_FT * 3 - vert_ft) / (SAFE_VERT_FT * 3)
        if hdg_delta < 45:
            risk += 0.2

        return min(risk / 2.0, 1.0)
    
    def _generate_suggestions(self, conflicts: List[tuple[str, str, float]], planes: List) -> List[tuple[str, str]]:
        suggestions = []
        for ac1, ac2, risk in conflicts:
            p1 = next((p for p in planes if p.callsign == ac1), None)
            p2 = next((p for p in planes if p.callsign == ac2), None)
            if not p1 or not p2:
                continue

            turn_dir = "L" if random.random() < 0.5 else "R"
            turn_deg = random.choice([10, 15, 20])
            new_hdg = (p1.hdg + (turn_deg if turn_dir == "R" else -turn_deg)) % 360
            cmd = f"HDG {int(new_hdg):03d}"
            suggestions.append((p1.callsign, cmd))
        return suggestions