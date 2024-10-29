from enum import Enum

class Steps(str, Enum):
    EVENT = "event"
    STATION = "station"
    WAVE = "wave"
    NONE = "none"