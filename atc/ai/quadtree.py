from __future__ import annotations
from typing import List, Tuple, Any, Optional
import dataclasses

@dataclasses.dataclass
class Quadtree:
    x: float
    y: float
    w: float
    h: float
    cap: int = 8
    depth: int = 0
    max_depth: int = 8
    points: List[Tuple[float, float, Any]] = dataclasses.field(default_factory=list)
    children: Optional[List[Quadtree]] = dataclasses.field(default=None, repr=False)

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)
    
    def insert(self, x: float, y: float, obj: Any) -> bool:
        bx, by, bw, bh = self.bounds
        if not (bx <= x <= bx + bw and by <= y <= by + bh):
            return False

        if (self.children is None and len(self.points) < self.cap) or self.depth >= self.max_depth:
            self.points.append((x, y, obj))
            return True

        if self.children is None:
            self._split()

        return any(child.insert(x, y, obj) for child in self.children)

    def _split(self) -> None:
        bx, by, bw, bh = self.bounds
        hw, hh = bw / 2, bh / 2
        self.children = [
            Quadtree(bx,     by,     hw, hh, self.cap, self.depth + 1, self.max_depth),
            Quadtree(bx+hw,  by,     hw, hh, self.cap, self.depth + 1, self.max_depth),
            Quadtree(bx,     by+hh,  hw, hh, self.cap, self.depth + 1, self.max_depth),
            Quadtree(bx+hw,  by+hh,  hw, hh, self.cap, self.depth + 1, self.max_depth),
        ]

        for px, py, obj in self.points:
            for child in self.children:
                if child.insert(px, py, obj):
                    break
        self.points.clear()

    def _query(self, x: float, y: float, r: float, out: List[Any]) -> None:
        bx, by, bw, bh = self.bounds

        cx = max(bx, min(x, bx + bw))
        cy = max(by, min(y, by + bh))
        if (cx - x)**2 + (cy - y)**2 > r**2:
            return

        if self.children is None:
            for px, py, obj in self.points:
                if (px - x)**2 + (py - y)**2 <= r**2:
                    out.append(obj)
        else:
            for child in self.children:
                child._query(x, y, r, out)

    def query_radius(self, x: float, y: float, r: float) -> List[Any]:
        """Return all objects within radius `r` of point (x, y)."""
        out: List[Any] = []
        self._query(x, y, r, out)
        return out