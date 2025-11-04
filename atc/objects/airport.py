import dataclasses
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .runway_v2 import Runway
    from .aircraft_v2 import Aircraft

@dataclasses.dataclass
class Airport:
    icao: str
    name: str
    runways: List["Runway"]
    arrivals: List["Aircraft"] = dataclasses.field(default_factory=list)

    def register_arrival(self, aircraft: "Aircraft"):
        if aircraft not in self.arrivals:
            self.arrivals.append(aircraft)
    
    def get_runway(self, name: str) -> Optional["Runway"]:
        return next((r for r in self.runways if r.name == name), None)
    
    def active_runways(self):
        return [r for r in self.runways if r.active_aircraft]
    
    def __repr__(self):
        return f"<Airport {self.icao} ({len(self.runways)} RWY), {len(self.arrivals)} arrivals)>"