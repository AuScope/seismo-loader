from pydantic import BaseModel
from typing import Optional, List, Union, Any
from datetime import date, timedelta, datetime
from enum import Enum
import os
import configparser
from configparser import ConfigParser

from obspy import UTCDateTime
from obspy.core.inventory import Inventory
from obspy.core.event import Catalog

from .common import RectangleArea, CircleArea
from seismic_data.enums.config import DownloadType, SeismoClients, GeoConstraintType, Levels, EventModels

# TODO: Not sure if these values are controlled values
# check to see if should we use controlled values or
# rely on free inputs from users.
from seismic_data.enums.stations import Channels, Stations, Locations, Networks

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
    
def convert_to_str(val):
    if isinstance(val, Enum):
        return str(val.value)
    if val:
        return str(val)
    return ''
            
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
    client           : Optional     [SeismoClients]   = SeismoClients.AUSPASS
    channel_pref     : Optional     [List[Channels]]  = []
    location_pref    : Optional     [List[Locations]] = []
    days_per_request : Optional     [int]             = 3


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
    client             : Optional   [ SeismoClients] = SeismoClients.AUSPASS
    force_stations     : Optional   [ List          [SeismoQuery]] = []
    exclude_stations   : Optional   [ List          [SeismoQuery]] = []
    date_config        : DateConfig = DateConfig    ()
    local_inventory    : Optional   [ str           ] = None
    network            : Optional   [ str           ] = None
    station            : Optional   [ str           ] = None
    location           : Optional   [ str           ] = None
    channel            : Optional   [ str           ] = None
    selected_invs      : Optional   [ List          [Any]] = []
    geo_constraint     : Optional   [ List          [GeometryConstraint]] = None
    include_restricted : bool       = False
    level              : Levels     = Levels        .CHANNEL

    class Config:
        json_encoders = {
            Any: lambda v: None  
        }
        exclude = {"selected_invs"}
    # TODO: check if it makes sense to use SeismoLocation instead of separate
    # props.
    # seismo_location: List[SeismoLocation] = None

    # FIXME: for now we just assume all values are 
    # given in one string separated with "," -> e.g.
    # channel = CH,HH,BH,EH

class EventConfig(BaseModel):
    client       : Optional   [SeismoClients] = SeismoClients.AUSPASS
    date_config  : DateConfig  = DateConfig()
    model        : EventModels = EventModels.IASP91
    min_depth    : float
    max_depth    : float
    min_magnitude: float
    max_magnitude: float
    # These are relative to the individual stations
    min_radius            : float         = 30
    max_radius            : float         = 90
    before_p_sec          : int           = 10
    after_p_sec           : int           = 10
    include_all_origins   : bool          = False
    include_all_magnitudes: bool          = False
    include_arrivals      : bool          = False
    limit                 : Optional[str] = None
    offset                : Optional[str] = None
    local_catalog         : Optional[str] = None
    contributor           : Optional[str] = None
    updated_after         : Optional[str] = None

    selected_catalogs     : Optional[List[Any]] = []

    geo_constraint: Optional[List[GeometryConstraint]] = None
    class Config:
        json_encoders = {
            Any: lambda v: None  
        }
        exclude = {"selected_catalogs"}


class SeismoLoaderSettings(BaseModel):
    sds_path     : str                        = None
    db_path      : str                        = None
    download_type: DownloadType               = DownloadType.EVENT
    proccess     : ProcessingConfig           = None
    auths        : Optional[List[AuthConfig]] = []
    waveform     : WaveformConfig             = None
    station      : StationConfig              = None
    event        : EventConfig                = None

    # main: Union[EventConfig, StationConfig] = None


    @classmethod
    def from_cfg_file(cls, cfg_path: str) -> "SeismoLoaderSettings":
        config = configparser.ConfigParser()
        cfg_path = os.path.abspath(cfg_path)

        config.read(cfg_path)

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
        client = SeismoClients[config.get('WAVEFORM', 'client', fallback='AUSPASS').upper()]
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
        geo_constraint_station = None
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
                    min_radius=config.getfloat('STATION', 'minradius', fallback=None),
                    max_radius=config.getfloat('STATION', 'maxradius', fallback=None)
                )
            )

        station_config = StationConfig(
            client=SeismoClients[station_client.upper()] if station_client else None,
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
            geo_constraint=[geo_constraint_station],
            include_restricted=config.get('STATION', 'includerestricted' , fallback=False),
            level = config.get('STATION', 'level' , fallback=None)
        )

        if download_type not in DownloadType:
            raise ValueError(f"Incorrect value for download_type. Possible values are: {DownloadType.EVENT} or {DownloadType.CONTIN}.")
            

        # Parse the EVENT section
        event_config = None
        if download_type == DownloadType.EVENT:
            event_client = config.get('EVENT', 'client', fallback=None    )
            model        = config.get('EVENT', 'model' , fallback='iasp91')

            # MAP SEARCH
            geo_constraint_event = None
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
                client                 = SeismoClients[event_client.upper()] if event_client else None,
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
                geo_constraint         = [geo_constraint_event],
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
        config['SDS'] = {
            'sds_path': self.sds_path
        }

        # Populate the [DATABASE] section
        config['DATABASE'] = {
            'db_path': convert_to_str(self.db_path)
        }

        # Populate the [PROCESSING] section
        config['PROCESSING'] = {
            'num_processes': convert_to_str(self.proccess.num_processes),
            'gap_tolerance': convert_to_str(self.proccess.gap_tolerance),
            'download_type': convert_to_str(self.download_type.value)
        }

        # Populate the [AUTH] section
        config['AUTH'] = {}
        if self.auths:
            for auth in self.auths:
                config['AUTH'][auth.nslc_code] = f"{auth.username}:{auth.password}"

        # Populate the [WAVEFORM] section
        config['WAVEFORM'] = {
            'client': convert_to_str(self.waveform.client.value),
            'channel_pref': ','.join([channel.value for channel in self.waveform.channel_pref]),
            'location_pref': ','.join([loc.value for loc in self.waveform.location_pref]),
            'days_per_request': convert_to_str(self.waveform.days_per_request)
        }


        if self.station:
            config['STATION'] = {
                'client': convert_to_str(self.station.client),
                'local_inventory': convert_to_str(self.station.local_inventory),
                'force_stations': ','.join([station.cmb_str for station in self.station.force_stations]),
                'exclude_stations': ','.join([station.cmb_str for station in self.station.exclude_stations]),
                'starttime': convert_to_str(self.station.date_config.start_time),
                'endtime': convert_to_str(self.station.date_config.end_time),
                'startbefore': convert_to_str(self.station.date_config.start_before),
                'startafter': convert_to_str(self.station.date_config.start_after),
                'endbefore': convert_to_str(self.station.date_config.end_before),
                'endafter': convert_to_str(self.station.date_config.end_after),
                'network': convert_to_str(self.station.network),
                'station': convert_to_str(self.station.station),
                'location': convert_to_str(self.station.location),
                'channel': convert_to_str(self.station.channel),
                'geo_constraint': convert_to_str(self.station.geo_constraint[0].geo_type),
            }

            # FIXME: The settings are updated such that they support multiple geometries.
            # But config file only accepts one geometry at a time. For now we just get
            # the first item.

            if self.station.geo_constraint[0].geo_type == GeoConstraintType.CIRCLE:
                config['STATION']['latitude']  = convert_to_str(self.station.geo_constraint[0].coords.lat)
                config['STATION']['longitude'] = convert_to_str(self.station.geo_constraint[0].coords.lng)
                config['STATION']['minradius'] = convert_to_str(self.station.geo_constraint[0].coords.min_radius)
                config['STATION']['maxradius'] = convert_to_str(self.station.geo_constraint[0].coords.max_radius)

            if self.station.geo_constraint[0].geo_type == GeoConstraintType.BOUNDING:
                config['STATION']['minlatitude']  = convert_to_str(self.station.geo_constraint[0].coords.min_lat)
                config['STATION']['maxlatitude']  = convert_to_str(self.station.geo_constraint[0].coords.max_lat)
                config['STATION']['minlongitude'] = convert_to_str(self.station.geo_constraint[0].coords.min_lng)
                config['STATION']['maxlongitude'] = convert_to_str(self.station.geo_constraint[0].coords.max_lng)

            config['STATION']['includerestricted'] = convert_to_str(self.station.include_restricted)
            config['STATION']['level']             = convert_to_str(self.station.level.value)

        # Check if the main section is EventConfig or StationConfig and populate accordingly
        if self.event:
            config['EVENT'] = {
                'client'               : convert_to_str(self.event.client                       ) ,
                'model'                : convert_to_str(self.event.model                        ) ,
                'min_depth'            : convert_to_str(self.event.min_depth                    ) ,
                'max_depth'            : convert_to_str(self.event.max_depth                    ) ,
                'minmagnitude'         : convert_to_str(self.event.min_magnitude                ) ,
                'maxmagnitude'         : convert_to_str(self.event.max_magnitude                ) ,
                'minradius'            : convert_to_str(self.event.min_radius                   ) ,
                'maxradius'            : convert_to_str(self.event.max_radius                   ) ,
                'after_p_sec'          : convert_to_str(self.event.after_p_sec                  ) ,
                'before_p_sec'         : convert_to_str(self.event.before_p_sec                 ) ,
                'includeallorigins'    : convert_to_str(self.event.include_all_origins          ) ,
                'includeallmagnitudes' : convert_to_str(self.event.include_all_magnitudes       ) ,
                'includearrivals'      : convert_to_str(self.event.include_arrivals             ) ,
                'limit'                : convert_to_str(self.event.limit                        ) ,
                'offset'               : convert_to_str(self.event.offset                       ) ,
                'local_catalog'        : convert_to_str(self.event.local_catalog                ) ,
                'contributor'          : convert_to_str(self.event.contributor                  ) ,
                'updatedafter'         : convert_to_str(self.event.updated_after                ) ,
            }

            # FIXME: The settings are updated such that they support multiple geometries.
            # But config file only accepts one geometry at a time.For now we just get
            # the first item.
            
            if self.event.geo_constraint[0].geo_type == GeoConstraintType.CIRCLE:
                config['EVENT']['geo_constraint']     = GeoConstraintType.CIRCLE.value
                config['EVENT']['latitude']        = convert_to_str(self.event.geo_constraint[0].coords.lat)
                config['EVENT']['longitude']       = convert_to_str(self.event.geo_constraint[0].coords.lng)
                config['EVENT']['minsearchradius'] = convert_to_str(self.event.geo_constraint[0].coords.min_radius)
                config['EVENT']['maxsearchradius'] = convert_to_str(self.event.geo_constraint[0].coords.max_radius)

            if self.event.geo_constraint[0].geo_type == GeoConstraintType.BOUNDING:
                config['EVENT']['geo_constraint']  = GeoConstraintType.BOUNDING.value
                config['EVENT']['minlatitude']  = convert_to_str(self.event.geo_constraint[0].coords.min_lat)
                config['EVENT']['maxlatitude']  = convert_to_str(self.event.geo_constraint[0].coords.max_lat)
                config['EVENT']['minlongitude'] = convert_to_str(self.event.geo_constraint[0].coords.min_lng)
                config['EVENT']['maxlongitude'] = convert_to_str(self.event.geo_constraint[0].coords.max_lng)

        return config