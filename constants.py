AI_TRAFFIC = False

WIDTH, HEIGHT = 1500, 600
FPS = 30
SIM_SPEED = 5.0

RADAR_CENTER = (WIDTH // 2, HEIGHT // 2)
SIDEBAR_WIDTH = 260
SIDEBAR_OFFSET = 10
RADAR_WIDTH = WIDTH - SIDEBAR_WIDTH

NM_PER_PX = 0.08
SAFE_LAT_NM = 3.0
SAFE_VERT_FT = 1000

LANDING_HEADING_OFFSET_DEG = 60
LANDING_HEIGHT_OFFSET_FT = 3000

ERROR_LOG_FILE = "error_log.txt"

FIXES = {
    "DPA":   {"x": 1200, "y": 250},
    "EON":   {"x": 800,  "y": 700},
    "FONTI": {"x": 300,  "y": 150},
    "OBK":   {"x": 300,  "y": 600},
}

RUNWAYS = [
    {"x": 0.5, "y": 0.6,  "bearing": 270, "length_nm": 2.5},
    {"x": 0.7, "y": 0.65, "bearing": 270, "length_nm": 2.5},
]

AIRLINES = {
    "British Airways": {
        "IATA": "BA",
        "ICAO": "BAW",
        "Callsign": "Speedbird",
    },
    "EasyJet": {
        "IATA": "U2",
        "ICAO": "EZY",
        "Callsign": "Easy",
    },
    "Loganair": {
        "IATA": "LM",
        "ICAO": "LOG",
        "Callsign": "Logan",
    },
    "Ryanair": {
        "IATA": "RK",
        "ICAO": "RUK",
        "Callsign": "Bluemax",
    },
    "Wizz Air": {
        "IATA": "W9",
        "ICAO": "WUK",
        "Callsign": "Wizz Go",
    },
}