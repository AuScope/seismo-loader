from enum import Enum
from .common import DescribedEnum

class DownloadType(str, Enum):
    EVENT  = 'event'
    CONTINUOUS = 'continuous'


class WorkflowType(DescribedEnum):
    EVENT_BASED = ("Event Based - Starting from Selecting Events", "Here, add a paragraph describing the Event-Based workflow")
    STATION_BASED = ("Station Based - Starting from Selecting Stations", "Here, add a paragraph describing the Station-Based workflow")
    CONTINUOUS = ("Requesting Continuous Data", "Here, add a paragraph describing the Continuous workflow")


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