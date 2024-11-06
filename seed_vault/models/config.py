from pydantic import BaseModel
import json
from typing import IO, Dict, Optional, List, Union, Any
from datetime import date, timedelta, datetime
from enum import Enum
import os
import configparser
from configparser import ConfigParser
import pickle

from obspy import UTCDateTime

from .common import RectangleArea, CircleArea
from seed_vault.enums.config import DownloadType, WorkflowType, GeoConstraintType, Levels, EventModels

# TODO: Not sure if these values are controlled values
# check to see if should we use controlled values or
# rely on free inputs from users.
from seed_vault.enums.stations import Channels, Locations
from seed_vault.utils.clients import load_extra_client, load_original_client


# Convert start and end times to datetime
def parse_time(time_str):
    try:
        return UTCDateTime(time_str).isoformat()
    except:
        time_formats = [
            '%Y,%m,%d',         # Format like '2014,2,1'
            '%Y%j',             # Julian day format like '2014001'
            '%Y,%m,%d,%H,%M,%S' # Format with time '2014,3,2,0,0,5'
        ]
        for time_format in time_formats:
            try:
                return datetime.strptime(time_str, time_format)
            except ValueError:
                continue
    return None
    
def safe_add_to_config(config, section, key, value):
    """Helper function to safely add key-value pairs to config."""
    try:
        config[section][key] = convert_to_str(value)
    except Exception as e:
        print(f"Failed to add {key} to {section}: {e}")

def convert_to_str(val):
    try:
        if val is None:
            return ''  # Convert None to empty string
        if isinstance(val, Enum):
            return str(val.value)  # Convert Enum values to string
        if isinstance(val, (str, int, float, bool)):
            return str(val)  # Convert valid types to string
        if hasattr(val, '__str__'):
            return str(val)  # Use __str__ for objects
        return repr(val)  # Use repr for unsupported objects
    except Exception as e:
        print(f"Error converting value {val}: {e}")
        return ''  # Return empty string if conversion fails
            
class ProcessingConfig(BaseModel):
    num_processes: Optional    [  int         ] = 4
    gap_tolerance: Optional    [  int         ] = 60
    logging      : Optional    [  str         ] = None

class AuthConfig(BaseModel):
    nslc_code: str  # network.station.location.channel code
    username: str
    password: str

class SeismoQuery(BaseModel):
    network : Optional[str] = None
    station : Optional[str] = None
    location: Optional[str] = None
    channel : Optional[str] = None
    starttime: Optional[datetime] = None
    endtime: Optional[datetime] = None

    def __init__(self, cmb_str_n_s=None, **data):
        super().__init__(**data) 
        if cmb_str_n_s:
            self.cmb_str_n_s_to_props(cmb_str_n_s)

    @property
    def cmb_str(self):
        cmb_str = ''
        if self.network:
            cmb_str += f"{self.network}."
        if self.station:
            cmb_str += f"{self.station}."
        if self.location:
            cmb_str += f"{self.location}."
        if self.channel:
            cmb_str += f"{self.channel}."
        
        if cmb_str.endswith("."):
            cmb_str = cmb_str[:-1]

        return cmb_str
    
    def cmb_str_n_s_to_props(self, cmb_n_s):
        network, station = cmb_n_s.split(".")
        setattr(self, 'network', network)
        setattr(self, 'station', station)

class DateConfig(BaseModel):
    start_time  : Optional[Union[date, Any] ] = date.today() - timedelta(days=7)
    end_time    : Optional[Union[date, Any] ] = date.today()
    start_before: Optional[Union[date, Any] ] =      None
    start_after : Optional[Union[date, Any] ] =      None
    end_before  : Optional[Union[date, Any] ] =      None
    end_after   : Optional[Union[date, Any] ] =      None


class WaveformConfig(BaseModel):
    client           : Optional     [str]   = "IRIS"
    channel_pref     : Optional     [List[Channels]]  = [
        Channels.CH, Channels.HH, Channels.BH, Channels.EH,
        Channels.HN, Channels.EN, Channels.SH, Channels.LH
    ]
    location_pref    : Optional     [List[Locations]] = [
        Locations("10"), Locations("00"), Locations("20"), Locations("30")
    ]
    days_per_request : Optional     [int]             = 1

    def set_default(self):
        """Resets all fields to their default values."""
        self.__fields_set__.clear()
        for field_name, field in self.__fields__.items():
            setattr(self, field_name, field.get_default())

class GeometryConstraint(BaseModel):
    geo_type: Optional[GeoConstraintType] = GeoConstraintType.NONE
    coords: Optional[Union[RectangleArea, CircleArea]] = None

    def __init__(self, **data):
        super().__init__(**data)
        if isinstance(self.coords, RectangleArea):
            self.geo_type = GeoConstraintType.BOUNDING
        elif isinstance(self.coords, CircleArea):
            self.geo_type = GeoConstraintType.CIRCLE
        else:
            self.geo_type = GeoConstraintType.NONE


class StationConfig(BaseModel):
    client             : Optional   [ str] = "IRIS"
    force_stations     : Optional   [ List          [SeismoQuery]] = []
    exclude_stations   : Optional   [ List          [SeismoQuery]] = []
    date_config        : DateConfig                                = DateConfig(
        start_time=datetime(2024, 8, 20),
        end_time=datetime(2024, 9, 20)
    )
    local_inventory    : Optional   [ str           ] = None
    network            : Optional   [ str           ] = None
    station            : Optional   [ str           ] = None
    location           : Optional   [ str           ] = None
    channel            : Optional   [ str           ] = None
    selected_invs      : Optional   [Any] = None
    geo_constraint     : Optional   [ List          [GeometryConstraint]] = None
    include_restricted : bool       = False
    level              : Levels     = Levels        .CHANNEL

    class Config:
        json_encoders = {
            Any: lambda v: None  
        }
        exclude = {"selected_invs"}

    def set_default(self):
        """Resets all fields to their default values."""
        self.__fields_set__.clear()
        for field_name, field in self.__fields__.items():
            setattr(self, field_name, field.get_default())

    # TODO: check if it makes sense to use SeismoLocation instead of separate
    # props.
    # seismo_location: List[SeismoLocation] = None

    # FIXME: for now we just assume all values are 
    # given in one string separated with "," -> e.g.
    # channel = CH,HH,BH,EH

class EventConfig(BaseModel):
    client              : Optional   [str] = "IRIS"
    date_config         : DateConfig                 = DateConfig(
        start_time=datetime(2024, 8, 20),
        end_time=datetime(2024, 9, 20)
    )
    model               : EventModels = EventModels.IASP91
    min_depth           : float = 0.0
    max_depth           : float = 6800.0
    min_magnitude       : float = 5.0
    max_magnitude       : float = 10.0
    min_radius          : float = 30.0
    max_radius          : float = 90.0
    before_p_sec        : int = 10
    after_p_sec         : int = 130
    include_all_origins : bool = False
    include_all_magnitudes: bool = False
    include_arrivals    : bool = False
    limit               : Optional[str] = None
    offset              : Optional[str] = None
    local_catalog       : Optional[str] = None
    contributor         : Optional[str] = None
    updated_after       : Optional[str] = None

    selected_catalogs   : Optional[Any] = None

    geo_constraint      : Optional[List[GeometryConstraint]] = None

    class Config:
        json_encoders = {
            Any: lambda v: None  
        }
        exclude = {"selected_catalogs"}

    def set_default(self):
        """Resets all fields to their default values."""
        self.__fields_set__.clear()
        for field_name, field in self.__fields__.items():
            setattr(self, field_name, field.get_default())      

class PredictionData(BaseModel):
    event_id: str
    station_id: str
    p_arrival: datetime
    s_arrival: datetime
class SeismoLoaderSettings(BaseModel):
    sds_path          : str                                   = None
    db_path           : str                                   = None
    download_type     : DownloadType                          = DownloadType.EVENT
    selected_workflow : WorkflowType                          = WorkflowType.EVENT_BASED
    proccess          : ProcessingConfig                      = None
    client_url_mapping: Optional[dict]                        = {}
    extra_clients     : Optional[dict]                        = {}
    auths             : Optional        [List[AuthConfig]]    = []
    waveform          : WaveformConfig                        = None
    station           : StationConfig                         = None
    event             : EventConfig                           = None
    predictions       : Dict            [str, PredictionData] = {}


    def load_url_mapping(self):
        from obspy.clients.fdsn.header import URL_MAPPINGS
        self.client_url_mapping = load_original_client()
        self.extra_clients = load_extra_client()
        self.client_url_mapping.update(self.extra_clients)
        URL_MAPPINGS.update(self.client_url_mapping)


    def set_download_type_from_workflow(self):
        if (
            self.selected_workflow == WorkflowType.EVENT_BASED or
            self.selected_workflow == WorkflowType.STATION_BASED
        ):
            self.download_type = DownloadType.EVENT

        if (self.selected_workflow == WorkflowType.CONTINUOUS):
            self.download_type = DownloadType.CONTINUOUS


    @classmethod
    def from_cfg_file(cls, cfg_source: Union[str, IO])  -> "SeismoLoaderSettings":
        config = configparser.ConfigParser()
        config.optionxform = str

        # If cfg_source is a string, assume it's a file path
        if isinstance(cfg_source, str):
            cfg_path = os.path.abspath(cfg_source)

            if not os.path.exists(cfg_path):
                raise ValueError(f"File not found in the following path: {cfg_path}")

            config.read(cfg_path)
        else:
            config.read_file(cfg_source)


        # Parse values from the [SDS] section
        sds_path = config.get('SDS', 'sds_path')

        # Parse the DATABASE section
        db_path = config.get('DATABASE', 'db_path', fallback=f'{sds_path}/database.sqlite')

        # Parse the PROCESSING section
        num_processes = config.getint('PROCESSING', 'num_processes', fallback=4)
        gap_tolerance = config.getint('PROCESSING', 'gap_tolerance', fallback=60)
        download_type_str = config.get('PROCESSING', 'download_type', fallback='event')
        download_type = DownloadType(download_type_str.lower())

        # Parse the AUTH section
        credentials = list(config['AUTH'].items())
        lst_auths   = []
        for nslc, cred in credentials:
            username, password = cred.split(':')
            lst_auths.append(
                AuthConfig(
                    nslc_code = nslc,
                    username = username,
                    password = password
                )
            )

        # Parse the WAVEFORM section
        client = config.get('WAVEFORM', 'client', fallback='IRIS').upper()
        channel_pref = config.get('WAVEFORM', 'channel_pref', fallback='').split(',')
        location_pref = config.get('WAVEFORM', 'location_pref', fallback='').split(',')
        days_per_request = config.getint('WAVEFORM', 'days_per_request', fallback=1)

        waveform = WaveformConfig(
            client = client,
            channel_pref=[Channels(channel.strip()) for channel in channel_pref if channel],
            location_pref=[Locations(loc.strip()) for loc in location_pref if loc],
            days_per_request=days_per_request
        )

        # STATION CONFIG
        # ==============================
        # Parse the STATION section
        station_client = config.get('STATION', 'client', fallback=None)

        force_stations_cmb_n_s   = config.get('STATION', 'force_stations', fallback='').split(',')
        force_stations           = []
        for cmb_n_s in force_stations_cmb_n_s:
            if cmb_n_s != '':
                force_stations.append(SeismoQuery(cmb_str_n_s=cmb_n_s))

        exclude_stations_cmb_n_s = config.get('STATION', 'exclude_stations', fallback='').split(',')
        exclude_stations         = []
        for cmb_n_s in exclude_stations_cmb_n_s:
            if cmb_n_s != '':
                exclude_stations.append(SeismoQuery(cmb_str_n_s=cmb_n_s))

        # MAP SEAARCH            
        geo_constraint_station = []
        if config.get('STATION', 'geo_constraint', fallback=None) == GeoConstraintType.BOUNDING:
            geo_constraint_station = GeometryConstraint(
                coords=RectangleArea(
                    min_lat=config.getfloat('STATION', 'minlatitude', fallback=None),
                    max_lat=config.getfloat('STATION', 'maxlatitude', fallback=None),
                    min_lng=config.getfloat('STATION', 'minlongitude', fallback=None),
                    max_lng=config.getfloat('STATION', 'maxlongitude', fallback=None)
                )
            )

        if config.get('STATION', 'geo_constraint', fallback=None) == GeoConstraintType.CIRCLE:
            geo_constraint_station = GeometryConstraint(
                coords=CircleArea(
                    lat=config.getfloat('STATION', 'latitude', fallback=None),
                    lng=config.getfloat('STATION', 'longitude', fallback=None),
                    min_radius=config.getfloat('STATION', 'minsearchradius', fallback=None),
                    max_radius=config.getfloat('STATION', 'maxsearchradius', fallback=None)
                )
            )


        station_config = StationConfig(
            client=station_client.upper() if station_client else None,
            local_inventory=config.get("STATION","local_inventory", fallback=None),
            force_stations=force_stations,
            exclude_stations=exclude_stations,
            date_config=DateConfig(
                start_time   = parse_time(config.get('STATION', 'starttime'  , fallback=None)),
                end_time     = parse_time(config.get('STATION', 'endtime'    , fallback=None)),                    
                start_before = parse_time(config.get('STATION', 'startbefore', fallback=None)),
                start_after  = parse_time(config.get('STATION', 'startafter' , fallback=None)),
                end_before   = parse_time(config.get('STATION', 'endbefore'  , fallback=None)),
                end_after    = parse_time(config.get('STATION', 'endafter'   , fallback=None)),
            ),
            network =config.get('STATION', 'network' , fallback=None),
            station =config.get('STATION', 'station' , fallback=None),
            location=config.get('STATION', 'location', fallback=None),
            channel =config.get('STATION', 'channel' , fallback=None),
            geo_constraint=[geo_constraint_station] if geo_constraint_station else [],
            include_restricted=config.get('STATION', 'includerestricted' , fallback=False),
            level = config.get('STATION', 'level' , fallback=None)
        )

        if download_type not in DownloadType:
            raise ValueError(f"Incorrect value for download_type. Possible values are: {DownloadType.EVENT} or {DownloadType.CONTINUOUS}.")
            

        # Parse the EVENT section
        event_config = None
        if not config.has_section("EVENT"):
            event_config = EventConfig()
            event_config.set_default()  
        else:    
            event_client = config.get('EVENT', 'client', fallback=None    )
            model        = config.get('EVENT', 'model' , fallback='iasp91')

            # MAP SEARCH
            geo_constraint_event = []
            if config.get('EVENT', 'geo_constraint', fallback=None) == GeoConstraintType.BOUNDING:
                geo_constraint_event = GeometryConstraint(
                    coords=RectangleArea(
                        min_lat=config.getfloat('EVENT', 'minlatitude', fallback=None),
                        max_lat=config.getfloat('EVENT', 'maxlatitude', fallback=None),
                        min_lng=config.getfloat('EVENT', 'minlongitude', fallback=None),
                        max_lng=config.getfloat('EVENT', 'maxlongitude', fallback=None)
                    )
                )

            if config.get('EVENT', 'geo_constraint', fallback=None) == GeoConstraintType.CIRCLE:
                geo_constraint_event = GeometryConstraint(
                    coords=CircleArea(
                        lat        = config.getfloat('EVENT', 'latitude', fallback=None),
                        lng        = config.getfloat('EVENT', 'longitude', fallback=None),
                        min_radius = config.getfloat('EVENT', 'minsearchradius', fallback=None),
                        max_radius = config.getfloat('EVENT', 'maxsearchradius', fallback=None)
                    )
                )

            event_config = EventConfig(
                client                 = event_client.upper() if event_client else None,
                model                  = EventModels[model.upper()],
                date_config            = DateConfig(
                    start_time         = parse_time(config.get('EVENT', 'starttime'  , fallback=None)),
                    end_time           = parse_time(config.get('EVENT', 'endtime'    , fallback=None)),
                ),
                min_depth              = config.getfloat('EVENT', 'min_depth', fallback=None),
                max_depth              = config.getfloat('EVENT', 'max_depth', fallback=None),
                min_magnitude          = config.getfloat('EVENT', 'minmagnitude', fallback=None),
                max_magnitude          = config.getfloat('EVENT', 'maxmagnitude', fallback=None),
                min_radius             = config.getfloat('EVENT', 'minradius', fallback=None),
                max_radius             = config.getfloat('EVENT', 'maxradius', fallback=None),
                before_p_sec           = config.get('STATION', 'before_p_sec' , fallback=False),
                after_p_sec            = config.get('STATION', 'after_p_sec' , fallback=False),
                geo_constraint=[geo_constraint_event] if geo_constraint_event else [],
                include_all_origins    = config.get('STATION', 'includeallorigins' , fallback=False),
                include_all_magnitudes = config.get('STATION', 'includeallmagnitudes' , fallback=False),
                include_arrivals       = config.get('STATION', 'includearrivals' , fallback=False),
                limit                  = config.get('STATION', 'limit' , fallback=None),
                offset                 = config.get('STATION', 'offset' , fallback=None),
                local_catalog          = config.get('STATION', 'local_catalog' , fallback=None),
                contributor            = config.get('STATION', 'contributor' , fallback=None),
                updatedafter           = config.get('STATION', 'updatedafter' , fallback=None),
            )

        # Return the populated SeismoLoaderSettings
        return cls(
            sds_path=sds_path,
            db_path=db_path,
            download_type=download_type,
            proccess=ProcessingConfig(
                num_processes=num_processes,
                gap_tolerance=gap_tolerance
            ),
            auths=lst_auths,
            waveform=waveform,
            station=station_config,
            event= event_config
        )
    
    def to_cfg(self) -> ConfigParser:
        config = ConfigParser()

        # Populate the [SDS] section
        config['SDS'] = {}
        safe_add_to_config(config, 'SDS', 'sds_path', self.sds_path)

        # Populate the [DATABASE] section
        config['DATABASE'] = {}
        safe_add_to_config(config, 'DATABASE', 'db_path', self.db_path)

        # Populate the [PROCESSING] section
        config['PROCESSING'] = {}
        safe_add_to_config(config, 'PROCESSING', 'num_processes', self.proccess.num_processes)
        safe_add_to_config(config, 'PROCESSING', 'gap_tolerance', self.proccess.gap_tolerance)
        safe_add_to_config(config, 'PROCESSING', 'download_type', self.download_type.value)

        # Populate the [AUTH] section
        config['AUTH'] = {}
        if self.auths:
            for auth in self.auths:
                safe_add_to_config(config, 'AUTH', auth.nslc_code, f"{auth.username}:{auth.password}")


        # Populate the [WAVEFORM] section
        config['WAVEFORM'] = {}
        safe_add_to_config(config, 'WAVEFORM', 'client', self.waveform.client)
        safe_add_to_config(config, 'WAVEFORM', 'channel_pref', ','.join([convert_to_str(channel.value) for channel in self.waveform.channel_pref]))
        safe_add_to_config(config, 'WAVEFORM', 'location_pref', ','.join([convert_to_str(loc.value) for loc in self.waveform.location_pref]))
        safe_add_to_config(config, 'WAVEFORM', 'days_per_request', self.waveform.days_per_request)

        # Populate the [STATION] section
        if self.station:
            config['STATION'] = {}
            safe_add_to_config(config, 'STATION', 'client', self.station.client)
            safe_add_to_config(config, 'STATION', 'local_inventory', self.station.local_inventory)
            safe_add_to_config(config, 'STATION', 'force_stations', ','.join([convert_to_str(station.cmb_str) for station in self.station.force_stations if station.cmb_str is not None]))
            safe_add_to_config(config, 'STATION', 'exclude_stations', ','.join([convert_to_str(station.cmb_str) for station in self.station.exclude_stations if station.cmb_str is not None]))
            safe_add_to_config(config, 'STATION', 'starttime', self.station.date_config.start_time)
            safe_add_to_config(config, 'STATION', 'endtime', self.station.date_config.end_time)
            safe_add_to_config(config, 'STATION', 'network', self.station.network)
            safe_add_to_config(config, 'STATION', 'station', self.station.station)
            safe_add_to_config(config, 'STATION', 'location', self.station.location)
            safe_add_to_config(config, 'STATION', 'channel', self.station.channel)
            safe_add_to_config(config, 'STATION', 'station', self.station.station)
            safe_add_to_config(config, 'STATION', 'location', self.station.location)  # Ensure location is added
            safe_add_to_config(config, 'STATION', 'channel', self.station.channel)    # Ensure channel is added


            # FIXME: The settings are updated such that they support multiple geometries.
            # But config file only accepts one geometry at a time. For now we just get
            # the first item.
            if self.station.geo_constraint and hasattr(self.station.geo_constraint[0], 'geo_type'):
                safe_add_to_config(config, 'STATION', 'geo_constraint', self.station.geo_constraint[0].geo_type)
                
                if self.station.geo_constraint[0].geo_type == GeoConstraintType.CIRCLE:
                    safe_add_to_config(config, 'STATION', 'latitude', self.station.geo_constraint[0].coords.lat)
                    safe_add_to_config(config, 'STATION', 'longitude', self.station.geo_constraint[0].coords.lng)
                    safe_add_to_config(config, 'STATION', 'minradius', self.station.geo_constraint[0].coords.min_radius)
                    safe_add_to_config(config, 'STATION', 'maxradius', self.station.geo_constraint[0].coords.max_radius)

                if self.station.geo_constraint[0].geo_type == GeoConstraintType.BOUNDING:
                    safe_add_to_config(config, 'STATION', 'minlatitude', self.station.geo_constraint[0].coords.min_lat)
                    safe_add_to_config(config, 'STATION', 'maxlatitude', self.station.geo_constraint[0].coords.max_lat)
                    safe_add_to_config(config, 'STATION', 'minlongitude', self.station.geo_constraint[0].coords.min_lng)
                    safe_add_to_config(config, 'STATION', 'maxlongitude', self.station.geo_constraint[0].coords.max_lng)

            safe_add_to_config(config, 'STATION', 'includerestricted', self.station.include_restricted)
            safe_add_to_config(config, 'STATION', 'level', self.station.level.value)

        # Check if the main section is EventConfig or StationConfig and populate accordingly
        if self.event:
            config['EVENT'] = {}
            safe_add_to_config(config, 'EVENT', 'client', self.event.client)
            safe_add_to_config(config, 'EVENT', 'min_depth', self.event.min_depth)
            safe_add_to_config(config, 'EVENT', 'max_depth', self.event.max_depth)
            safe_add_to_config(config, 'EVENT', 'minmagnitude', self.event.min_magnitude)
            safe_add_to_config(config, 'EVENT', 'maxmagnitude', self.event.max_magnitude)
            safe_add_to_config(config, 'EVENT', 'minradius', self.event.min_radius)
            safe_add_to_config(config, 'EVENT', 'maxradius', self.event.max_radius)
            safe_add_to_config(config, 'EVENT', 'after_p_sec', self.event.after_p_sec)
            safe_add_to_config(config, 'EVENT', 'before_p_sec', self.event.before_p_sec)
            safe_add_to_config(config, 'EVENT', 'includeallorigins', self.event.include_all_origins)
            safe_add_to_config(config, 'EVENT', 'includeallmagnitudes', self.event.include_all_magnitudes)
            safe_add_to_config(config, 'EVENT', 'includearrivals', self.event.include_arrivals)
            safe_add_to_config(config, 'EVENT', 'limit', self.event.limit)
            safe_add_to_config(config, 'EVENT', 'offset', self.event.offset)
            safe_add_to_config(config, 'EVENT', 'local_catalog', self.event.local_catalog)
            safe_add_to_config(config, 'EVENT', 'contributor', self.event.contributor)
            safe_add_to_config(config, 'EVENT', 'updatedafter', self.event.updated_after)

            # FIXME: The settings are updated such that they support multiple geometries.
            # But config file only accepts one geometry at a time.For now we just get
            # the first item.
         
            if self.event.geo_constraint and hasattr(self.event.geo_constraint[0], 'geo_type'):
                safe_add_to_config(config, 'EVENT', 'geo_constraint', self.event.geo_constraint[0].geo_type)

                if self.event.geo_constraint[0].geo_type == GeoConstraintType.CIRCLE:
                    safe_add_to_config(config, 'EVENT', 'latitude', self.event.geo_constraint[0].coords.lat)
                    safe_add_to_config(config, 'EVENT', 'longitude', self.event.geo_constraint[0].coords.lng)
                    safe_add_to_config(config, 'EVENT', 'minsearchradius', self.event.geo_constraint[0].coords.min_radius)
                    safe_add_to_config(config, 'EVENT', 'maxsearchradius', self.event.geo_constraint[0].coords.max_radius)

                if self.event.geo_constraint[0].geo_type == GeoConstraintType.BOUNDING:
                    safe_add_to_config(config, 'EVENT', 'minlatitude', self.event.geo_constraint[0].coords.min_lat)
                    safe_add_to_config(config, 'EVENT', 'maxlatitude', self.event.geo_constraint[0].coords.max_lat)
                    safe_add_to_config(config, 'EVENT', 'minlongitude', self.event.geo_constraint[0].coords.min_lng)
                    safe_add_to_config(config, 'EVENT', 'maxlongitude', self.event.geo_constraint[0].coords.max_lng)

        return config

    def add_to_config(self):
        config_dict = {
            'sds_path': self.sds_path,
            'db_path': self.db_path,
            'num_processes': self.proccess.num_processes,
            'gap_tolerance': self.proccess.gap_tolerance,
            'download_type': self.download_type.value if self.download_type else None,
            'auths': self.auths if self.auths else [],
            'waveform': {
                'client': self.waveform.client if self.waveform and self.waveform.client else None,
                'channel_pref': [channel.value for channel in self.waveform.channel_pref] if self.waveform and isinstance(self.waveform.channel_pref, list) else [],
                'location_pref': [loc.value for loc in self.waveform.location_pref] if self.waveform and isinstance(self.waveform.location_pref, list) else [],
                'days_per_request': self.waveform.days_per_request if self.waveform and self.waveform.days_per_request is not None else None,
            },
            'station': {
                'client': self.station.client if self.station and self.station.client else None,
                'local_inventory': self.station.local_inventory if self.station else None,
                'force_stations': [station.cmb_str for station in self.station.force_stations if station.cmb_str is not None] if self.station and isinstance(self.station.force_stations, list) else [],
                'exclude_stations': [station.cmb_str for station in self.station.exclude_stations if station.cmb_str is not None] if self.station and isinstance(self.station.exclude_stations, list) else [],
                'starttime': self.station.date_config.start_time if self.station and self.station.date_config else None,
                'endtime': self.station.date_config.end_time if self.station and self.station.date_config else None,
                'startbefore': self.station.date_config.start_before if self.station and self.station.date_config else None,
                'startafter': self.station.date_config.start_after if self.station and self.station.date_config else None,
                'endbefore': self.station.date_config.end_before if self.station and self.station.date_config else None,
                'endafter': self.station.date_config.end_after if self.station and self.station.date_config else None,
                'network': self.station.network if self.station else None,
                'station': self.station.station if self.station else None,
                'location': self.station.location if self.station else None,
                'channel': self.station.channel if self.station else None,
                'geo_constraint': self.station.geo_constraint if self.station else None,
                'includerestricted': self.station.include_restricted if self.station else None,
                'level': self.station.level.value if self.station and self.station.level else None,
            },
            'event': {
                'client': self.event.client if self.event and self.event.client else None,
                'model': self.event.model.value if self.event and self.event.model else None,
                'before_p_sec': self.event.before_p_sec if self.event and self.event.before_p_sec is not None else None,
                'after_p_sec': self.event.after_p_sec if self.event and self.event.after_p_sec is not None else None,
                'starttime': self.event.date_config.start_time if self.event and self.event.date_config else None,
                'endtime': self.event.date_config.end_time if self.event and self.event.date_config else None,
                'min_depth': self.event.min_depth if self.event and self.event.min_depth is not None else None,
                'max_depth': self.event.max_depth if self.event and self.event.max_depth is not None else None,
                'minmagnitude': self.event.min_magnitude if self.event and self.event.min_magnitude is not None else None,
                'maxmagnitude': self.event.max_magnitude if self.event and self.event.max_magnitude is not None else None,
                'minradius': self.event.min_radius if self.event and self.event.min_radius is not None else None,
                'maxradius': self.event.max_radius if self.event and self.event.max_radius is not None else None,
                'local_catalog': self.event.local_catalog if self.event else None,
                'geo_constraint': self.event.geo_constraint if self.event else None,
                'includeallorigins': self.event.include_all_origins if self.event else None,
                'includeallmagnitudes': self.event.include_all_magnitudes if self.event else None,
                'includearrivals': self.event.include_arrivals if self.event else None,
                'limit': self.event.limit if self.event and self.event.limit is not None else None,
                'offset': self.event.offset if self.event and self.event.offset is not None else None,
                'contributor': self.event.contributor if self.event else None,
                'updatedafter': self.event.updated_after if self.event else None,
            }
        }
        return config_dict


    def add_prediction(self, event_id: str, station_id: str, p_arrival: datetime, s_arrival: datetime):
        key = f"{event_id}|{station_id}"
        self.predictions[key] = PredictionData(
            event_id=event_id,
            station_id=station_id,
            p_arrival=p_arrival,
            s_arrival=s_arrival
        )

    def get_prediction(self, event_id: str, station_id: str) -> Optional[PredictionData]:
        key = f"{event_id}|{station_id}"
        return self.predictions.get(key)
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    def to_pickle(self, pickle_path: str) -> None:
        """Serialize the SeismoLoaderSettings instance to a pickle file."""
        with open(pickle_path, "wb") as f:
            pickle.dump(self, f)
    
    @classmethod
    def from_pickle_file(cls, pickle_path: str) -> "SeismoLoaderSettings":
        """Load a SeismoLoaderSettings instance from a pickle file."""
        with open(pickle_path, "rb") as f:
            return pickle.load(f)        