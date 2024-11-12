from enum import Enum
from .common import DescribedEnum

class DownloadType(str, Enum):
    EVENT  = 'event'
    CONTINUOUS = 'continuous'


class WorkflowType(DescribedEnum):
    EVENT_BASED = ("Event Based - Starting from Selecting Events", "Search for events, then filter for pertinent stations")
    STATION_BASED = ("Station Based - Starting from Selecting Stations", "Search for stations, then filter for pertinent events")
    CONTINUOUS = ("Requesting Continuous Data", "Search for and download bulk continuous station data")


class GeoConstraintType(str, Enum):
    BOUNDING = 'bounding'
    CIRCLE   = 'circle'
    NONE     = 'neither'


class Levels(str, Enum):
    CHANNEL  = 'channel'
    # LOCATION = 'location'
    STATION  = 'station'
    # NETWORK  = 'network'


class EventModels(str, Enum):
    IASP91 = 'iasp91'
