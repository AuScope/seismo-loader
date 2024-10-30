#!/usr/bin/env python3

import os
import sys
import time
import sqlite3
import datetime
import multiprocessing
import configparser
import pandas as pd
from tqdm import tqdm
from tabulate import tabulate # non-standard. this is just to display the db contents
import random
from typing import List
from collections import defaultdict
import fnmatch

import obspy
from obspy.clients.fdsn import Client
from obspy import UTCDateTime
from obspy.taup import TauPyModel
from obspy.core.inventory import Inventory
from obspy.core.event import Catalog
from obspy.geodetics.base import locations2degrees,gps2dist_azimuth

from seed_vault.models.config import SeismoLoaderSettings, SeismoQuery
from seed_vault.enums.config import DownloadType, GeoConstraintType
from seed_vault.service.utils import is_in_enum
from seed_vault.service.db import DatabaseManager
#from seed_vault.service.db import setup_database, safe_db_connection # legacy imports, can soon remove
from seed_vault.service.waveform import get_local_waveform, stream_to_dataframe

### request status codes (TBD more:
# 204 = no data
# ??4 = denied

class CustomConfigParser(configparser.ConfigParser):
    def __init__(self, *args, **kwargs):
        self.case_sensitive_sections = set()
        super().__init__(*args, **kwargs)

    def optionxform(self, optionstr):
        return optionstr  # Always return the original string

def read_config(config_file):
    config = CustomConfigParser(allow_no_value=True)
    config.read(config_file)
    
    # Process the config, preserving case for [AUTH] and converting others to lowercase
    processed_config = CustomConfigParser(allow_no_value=True)
    
    for section in config.sections():
        processed_config.add_section(section)
        for key, value in config.items(section):
            if section in ['AUTH','DATABASE','SDS','WAVEFORM']:
                processed_key = key
                processed_value = value if value is not None else None
            else:
                # Convert to lowercase for other sections
                processed_key = key.lower()
                processed_value = value.lower() if value is not None else None
            
            processed_config.set(section, processed_key, processed_value)

    return processed_config

def to_timestamp(time_obj):
    """ Anything to timestamp helper """
    if isinstance(time_obj, (int, float)):
        return float(time_obj)
    elif isinstance(time_obj, datetime):
        return time_obj.timestamp()
    elif isinstance(time_obj, UTCDateTime):
        return time_obj.timestamp
    else:
        raise ValueError(f"Unsupported time type: {type(time_obj)}")


def miniseed_to_db_element(file_path):
    "Create a database element from a miniseed file"
    try:
        file = os.path.basename(file_path)
        parts = file.split('.')
        if len(parts) != 7:
            return None  # Skip files that don't match expected format
        
        network, station, location, channel, _, year, dayfolder = parts
        
        # Read the file to get actual start and end times
        st = obspy.read(file_path, headonly=True)
        
        if len(st) == 0:
            print(f"Warning: No traces found in {file_path}")
            return None
        
        start_time = min(tr.stats.starttime for tr in st)
        end_time = max(tr.stats.endtime for tr in st)
        
        return (network, station, location, channel,
            start_time.isoformat(), end_time.isoformat())
    
    except Exception as e:
        print(f"Error processing file {file_path}: {str(e)}")
        return None

def stream_to_db_element(st):
    """Create a database element from a stream 
    (assuming all traces have same NSLC!)
    just a bit faster than re-opening the file 
    again via miniseed_to_db_element"""

    if len(st) == 0:
        print(f"Warning: No traces found in {file_path}")
        return None
        
    start_time = min(tr.stats.starttime for tr in st)
    end_time = max(tr.stats.endtime for tr in st)
        
    return (st[0].stats.network, st[0].stats.station, \
        st[0].stats.location, st[0].stats.channel, \
         start_time.isoformat(), end_time.isoformat())


def populate_database_from_sds(sds_path, db_path,
    search_patterns=["??.*.*.???.?.????.???"],
    newer_than=None,num_processes=None):

    """Utility function to populate the archive_table in our database """

    db_manager = DatabaseManager(db_path)

    # Set to possibly the maximum number of CPUs!
    if num_processes is None:
        num_processes = multiprocessing.cpu_count()
    
    # Convert newer_than (means to filter only new files) to timestamp
    if newer_than:
        newer_than = to_timestamp(newer_than)

    # Collect all file paths
    file_paths = []

    for root, dirs, files in os.walk(sds_path,followlinks=True):
        for f in files:
            if any(fnmatch.fnmatch(f, pattern) for pattern in search_patterns):
                file_path = os.path.join(root,f)
                if newer_than is None or os.path.getmtime(file_path) > newer_than:
                    file_paths.append(os.path.join(root, f))
    
    total_files = len(file_paths)
    print(f"Found {total_files} files to process.")
    
    # Process files with or without multiprocessing (currently having issues with OSX and undoubtably windows is going to be a bigger problem TODO TODO)
    if num_processes > 1:
        try:
            with multiprocessing.Pool(processes=num_processes) as pool:
                to_insert_db = list(tqdm(pool.imap(miniseed_to_db_element, file_paths), \
                    total=total_files, desc="Processing files"))
        except Exception as e:
            print(f"Multiprocessing failed: {str(e)}. Falling back to single-process execution.")
            num_processes = 1
    else:
        to_insert_db = []
        for fp in tqdm(file_paths, desc="Scanning %s..." % sds_path):
            to_insert_db.append(miniseed_to_db_element(fp))

    # Update database
    try:
        num_inserted = db_manager.bulk_insert_archive_data(to_insert_db)
    except Exception as e:
        print("Error with bulk_insert_archive_data: ", e)    

    print(f"Processed {total_files} files, inserted {num_inserted} records into the database.")


#### now moved to db.py as part of DatabaseManager class
def join_continuous_segments(db_manager, gap_tolerance=60):
    """
    Join continuous data segments in the database, even across day boundaries.
    
    :param db_manager: DatabaseManager instance
    :param gap_tolerance: Maximum allowed gap (in seconds) to still consider segments continuous
    """
    with db_manager.connection() as conn:
        cursor = conn.cursor()
        
        # Fetch all data sorted by network, station, location, channel, and starttime
        cursor.execute('''
            SELECT id, network, station, location, channel, starttime, endtime
            FROM archive_data
            ORDER BY network, station, location, channel, starttime
        ''')
        
        all_data = cursor.fetchall()
        
        to_delete = []
        to_update = []
        current_segment = None
        
        for row in all_data:
            id, network, station, location, channel, starttime, endtime = row
            starttime = UTCDateTime(starttime)
            endtime = UTCDateTime(endtime)
            
            if current_segment is None:
                current_segment = list(row)
            else:
                # Check if this segment is continuous with the current one
                if (network == current_segment[1] and
                    station == current_segment[2] and
                    location == current_segment[3] and
                    channel == current_segment[4] and
                    starttime - UTCDateTime(current_segment[6]) <= gap_tolerance):
                    
                    # Extend the current segment
                    current_segment[6] = max(endtime, UTCDateTime(current_segment[6])).isoformat()
                    to_delete.append(id)
                else:
                    # Start a new segment
                    to_update.append(tuple(current_segment))
                    current_segment = list(row)
        
        # Don't forget the last segment
        if current_segment:
            to_update.append(tuple(current_segment))
        
        # Perform the updates
        cursor.executemany('''
            UPDATE archive_data
            SET endtime = ?
            WHERE id = ?
        ''', [(row[6], row[0]) for row in to_update])
        
        # Delete the merged segments
        if to_delete:
            cursor.execute(f'''
                DELETE FROM archive_data
                WHERE id IN ({','.join('?' * len(to_delete))})
            ''', to_delete)
        
    print(f"Joined segments. Deleted {len(to_delete)} rows, updated {len(to_update)} rows.")


# Requests for Continuous Data
def collect_requests(inv, time0, time1, days_per_request=3):
    """ Collect all requests required to download everything in inventory, split into X-day periods """
    requests = []  # network, station, location, channel, starttime, endtime

    for net in inv:
        for sta in net:
            for cha in sta:
                start_date = max(time0, cha.start_date.date)
                if cha.end_date:
                    end_date = min(time1 - (1/cha.sample_rate), cha.end_date.date + datetime.timedelta(days=1))
                else:
                    end_date = time1
                
                current_start = start_date
                while current_start < end_date:
                    current_end = min(current_start + datetime.timedelta(days=days_per_request), end_date)
                    
                    requests.append((
                        net.code,
                        sta.code,
                        cha.location_code,
                        cha.code,
                        current_start.isoformat() + "Z",
                        current_end.isoformat() + "Z" ))
                    
                    current_start = current_end
    return requests

# Requests for shorter, event-based data
def get_p_s_times(eq, dist_deg, ttmodel):
    #eq_lat = eq.origins[0].latitude
    #eq_lon = eq.origins[0].longitude
    eq_time = eq.origins[0].time
    eq_depth = eq.origins[0].depth / 1000  # depths are in meters for QuakeML
    try:
        phasearrivals = ttmodel.get_travel_times(
            source_depth_in_km=eq_depth,
            distance_in_degree=dist_deg,
            phase_list=['ttbasic'] #can't just look for "P" and "S" as they may not be found depending on distance
        )
    except Exception as e:
        print(f"Error calculating travel times: {str(e)}")
        return None, None
    p_arrival_time = None
    s_arrival_time = None
    # "P" is Whatever the first arrival is.. not necessarily literally uppercase P
    if phasearrivals[0]:
        p_arrival_time = eq_time + phasearrivals[0].time
    # Now get S... (or s for local)... (or nothing if > 100deg)
    for arrival in phasearrivals:
        if arrival.name.upper() == 'S' and s_arrival_time is None:
            s_arrival_time = eq_time + arrival.time
        if p_arrival_time and s_arrival_time:
            break
    if p_arrival_time is None:
        print(f"No direct P-wave arrival found for distance {dist_deg} degrees")
    if s_arrival_time is None:
        print(f"No direct S-wave arrival found for distance {dist_deg} degrees")
    return p_arrival_time, s_arrival_time

def select_highest_samplerate(inv, time=None, minSR=10):
    """
    Where overlapping channels exist (e.g. 100 hz and 10 hz), filter out anything other than highest available samplerate.
    Presumably, users will always want the highest samplerate for events.
    Best to set time, otherwise will remove regardless of time.
    """
    if time:
        inv = inv.select(time=time)
    for net in inv:
        for sta in net:
            srs = list(set([ele.sample_rate for ele in sta.channels]))
            if len(srs) < 2:
                continue
            sta.channels = [
                ele for ele in sta.channels 
                if ele.sample_rate == max(srs) and ele.sample_rate > minSR
            ]
    return inv

# TODO function to sort by maximum available sampling rate (have written this already somewhere)
cha_rank = ['CH','HH','BH','EH','HN','EN','SH','LH']
loc_rank = ['','10','00','20'] # sort of dangerous as no one does these in the same way
def TOFIX__output_best_channels(nn,sta,t):
        if type(sta) != obspy.core.inventory.station.Station:
                print("get_best_nslc: not station input!")
                return sta.channels
        if len(sta) <=1 : return sta.channels
        CHs = set([ele.code[0:2] for ele in sta.channels])
        if len(CHs) == 1:
                return [sta.channels[0]]

        # Re-assess what channels are avail. these should be sorted by samplerate with the highest first. that should be enough for most cases, but...

        for cha in sta.channels:
            if cha.end_date is None: cha.end_date = UTCDateTime(2099,1,1) # Easiest to replace all "None" with "far off into future"
        CHs = set([tr.stats.channel[0:2] for tr in st])
        for ch in cha_rank:
            selection = [ele for ele in sta.channels if ele.code[0:2] == ch and ele.start_date <= t <= ele.end_date]
            if selection: return selection
        print("no valid channels found in output_best_channels")
        return []

def collect_requests_event__OLD(eq, inv, min_dist_deg=30, max_dist_deg=90, 
                           before_p_sec=20, after_p_sec=160, model=None):
    """
    Collect all requests for data in inventory for given event eq.
    
    Args:
        eq: An earthquake object (one element of the array collected in a "catalog" object)
        inv: Inventory object
        min_dist_deg: Minimum distance in degrees
        max_dist_deg: Maximum distance in degrees
        before_p_sec: Seconds before P wave arrival
        after_p_sec: Seconds after P wave arrival
        model: Velocity model for travel time calculations
    
    Returns:
        Tuple of requests_per_eq and arrivals_per_eq
    """
    origin = eq.origins[0]  # Default to the primary origin
    ot = origin.time
    sub_inv = select_highest_samplerate(inv, time=ot)
    requests_per_eq = []
    arrivals_per_eq = []

    # Failsafe to ensure a model is loaded
    if not model:
        model = TauPyModel('IASP91')

    for net in sub_inv:
        for sta in net:
            # Check if we've already calculated this event-station pair
            fetched_arrivals = db_manager.fetch_arrivals(
                str(eq.preferred_origin_id), net.code, sta.code
            )
            
            if fetched_arrivals:
                p_time, s_time = fetched_arrivals  # timestamps
                t_start = p_time - abs(before_p_sec)
                t_end = s_time + abs(after_p_sec)
            else:
                dist_deg = locations2degrees(
                    origin.latitude, origin.longitude, sta.latitude, sta.longitude
                )
                dist_m, azi, backazi = gps2dist_azimuth(
                    origin.latitude, origin.longitude, sta.latitude, sta.longitude
                )
                
                if dist_deg < min_dist_deg or dist_deg > max_dist_deg:
                    continue
                
                p_time, s_time = get_p_s_times(eq, dist_deg, sta.latitude, sta.longitude, model)
                
                if not p_time:
                    continue  # TODO:need error msg also
                
                t_start = (p_time - abs(before_p_sec)).timestamp()
                t_end = (p_time + abs(after_p_sec)).timestamp()
                
                # Add to our arrival database
                arrivals_per_eq.append((
                    str(eq.preferred_origin_id),
                    eq.magnitudes[0].mag,
                    origin.latitude, origin.longitude, origin.depth / 1000,
                    ot.timestamp,
                    net.code, sta.code, sta.latitude, sta.longitude, sta.elevation / 1000,
                    sta.start_date.timestamp(), sta.end_date.timestamp(),
                    dist_deg, dist_m / 1000, azi, p_time.timestamp(),
                    s_time.timestamp(), settings.event.model 
                ))

            # Add to our requests
            for cha in sta:  # TODO: will have to filter channels prior to this, else will grab them all
                requests_per_eq.append((
                    net.code,
                    sta.code,
                    cha.location_code,
                    cha.code,
                    datetime.datetime.fromtimestamp(t_start).isoformat() + "Z",
                    datetime.datetime.fromtimestamp(t_end).isoformat() + "Z"
                ))

    return requests_per_eq, arrivals_per_eq


def collect_requests_event(eq,inv,min_dist_deg=30,max_dist_deg=90,before_p_sec=20,after_p_sec=160,model=None,settings=None):
    """ 
    @Review: Rob please review this
    
    This method is revised as followings:

    1. No more need for params: `min_dist_deg` and `max_dist_deg`. This function will accept a shortlist of selected 
    events and stations.
    """
    settings, db_manager = setup_paths(settings)
    origin = eq.origins[0] # default to the primary I suppose (possible TODO but don't see why anyone would want anything else)
    ot = origin.time
    sub_inv = inv.select(time = ot) # Loose filter to select only stations that were running during the earthquake start
    before_p_sec = settings.event.before_p_sec
    after_p_sec = settings.event.after_p_sec
    # Failsafe to ensure a model is loaded
    if not model:
        model = TauPyModel('IASP91')

    # TODO: further filter by selecting best available channels

    requests_per_eq = []
    arrivals_per_eq = []
    p_arrivals = {}  # Dictionary to store P arrivals

    for net in sub_inv:
        for sta in net:
            try:
                sta_start = sta.start_date.timestamp
                sta_end = sta.end_date.timestamp
            except:
                sta_start = None
                sta_end = None
            # Check if we've already calculated this event-station pair
            fetched_arrivals = db_manager.fetch_arrivals(str(eq.preferred_origin_id), \
                               net.code,sta.code) #TODO also check models are consistent? not critical. in fact we might be better off just forcing everything to IASP91
            if fetched_arrivals:
                p_time,s_time = fetched_arrivals # timestamps
                t_start = p_time - abs(before_p_sec)
                t_end = s_time + abs(after_p_sec)
                # add the already-fetched arrivals to our dictionary
                p_arrivals[f"{net.code}.{sta.code}"] = p_time
            else:
                dist_deg = locations2degrees(origin.latitude,origin.longitude,\
                                             sta.latitude,sta.longitude)
                dist_m,azi,backazi = gps2dist_azimuth(origin.latitude,origin.longitude,\
                                             sta.latitude,sta.longitude)
                # if dist_deg < min_dist_deg or dist_deg > max_dist_deg:
                #     continue
                
                p_time, s_time = get_p_s_times(eq,dist_deg,model)
                if p_time is None:
                    print(f"Warning: Unable to calculate P time for {net.code}.{sta.code}")
                    continue
                t_start = p_time - abs(before_p_sec) #not timestamps!
                t_end = p_time + abs(after_p_sec)
                p_arrivals[f"{net.code}.{sta.code}"] = p_time.timestamp
                t_start = t_start.timestamp
                t_end = t_end.timestamp
                # Add to our arrival database
                arrivals_per_eq.append((str(eq.preferred_origin_id),
                                    eq.magnitudes[0].mag,
                                    origin.latitude, origin.longitude,origin.depth/1000,
                                    ot.timestamp,
                                    net.code,sta.code,sta.latitude,sta.longitude,sta.elevation/1000,
                                    sta_start,sta_end,
                                    dist_deg,dist_m/1000,azi,p_time.timestamp,
                                    s_time.timestamp,settings.event.model))
            # Add to our requests
            for cha in sta: # TODO will have to had filtered channels prior to this, else will grab them all
                requests_per_eq.append((
                    net.code,
                    sta.code,
                    cha.location_code,
                    cha.code,
                    # fix the time difference, it will always have 8 hours difference. 
                    datetime.datetime.fromtimestamp(t_start, tz=datetime.timezone.utc).isoformat(),
                    datetime.datetime.fromtimestamp(t_end, tz=datetime.timezone.utc).isoformat() ))

    return requests_per_eq, arrivals_per_eq, p_arrivals


def combine_requests(requests):
    """
    Combine requests to reduce the volume of requests to the server
    """

    # Group requests by network and time range
    groups = defaultdict(list)
    for net, sta, loc, chan, t0, t1 in requests:
        groups[(net, t0, t1)].append((sta, loc, chan))
    
    # Combine requests for each group
    combined_requests = []
    for (net, t0, t1), items in groups.items():
        # Combine stations, locations, and channels
        stas = set()
        locs = set()
        chans = set()
        for sta, loc, chan in items:
            stas.add(sta)
            locs.add(loc)
            chans.add(chan)
        
        # Create the combined request
        combined_requests.append((
            net,
            ','.join(sorted(stas)),
            ','.join(sorted(locs)),
            ','.join(sorted(chans)),
            t0,
            t1
        ))
    
    return combined_requests

def prune_requests(requests, db_manager, min_request_window=3):
    """
    Remove any overlapping requests where already-archived data may exist.
    Ignore requests that are less than min_request_window seconds.
    
    Args:
        requests: List of request tuples (network, station, location, channel, start_time, end_time)
        db_manager: DatabaseManager instance
        min_request_window: Minimum request window in seconds (default: 3)
    
    Returns:
        List of pruned request tuples
    """
    pruned_requests = []
    
    with db_manager.connection() as conn:
        cursor = conn.cursor()
        
        for req in requests:
            network, station, location, channel, start_time, end_time = req
            start_time = UTCDateTime(start_time)
            end_time = UTCDateTime(end_time)
            
            # Query the database for existing data
            cursor.execute('''
                SELECT starttime, endtime FROM archive_data
                WHERE network = ? AND station = ? AND location = ? AND channel = ?
                AND endtime >= ? AND starttime <= ?
                ORDER BY starttime
            ''', (network, station, location, channel, start_time.isoformat(), end_time.isoformat()))
            
            existing_data = cursor.fetchall()
            
            if not existing_data:
                # If no existing data, keep the entire request
                pruned_requests.append(req)
            else:
                # Process gaps in existing data
                current_time = start_time
                for db_start, db_end in existing_data:
                    db_start = UTCDateTime(db_start)
                    db_end = UTCDateTime(db_end)
                    
                    if current_time < db_start - min_request_window:
                        # There's a gap before this existing data
                        pruned_requests.append((
                            network, station, location, channel, 
                            current_time.isoformat(), db_start.isoformat()
                        ))
                    
                    current_time = max(current_time, db_end)
                
                if current_time < end_time - min_request_window:
                    # There's a gap after the last existing data
                    pruned_requests.append((
                        network, station, location, channel, 
                        current_time.isoformat(), end_time.isoformat()
                    ))

    # Sort by start time, network, station
    pruned_requests.sort(key=lambda x: (x[4], x[0], x[1]))
    
    return pruned_requests


def archive_request(request, waveform_clients, sds_path, db_manager):
    """ Send a request to an FDSN center, parse it, save to archive, and update database """
    try:
        # if request[0] in waveform_clients.keys():  # Per-network authentication
        #     wc = waveform_clients[request[0]]
        # elif request[0]+'.'+request[1] in waveform_clients.keys():  # Per-station e.g. NN.SSSSS
        #     wc = waveform_clients[request[0]+'.'+request[1]]
        # else:
        #     wc = waveform_clients['open']

        kwargs = {
            'network':request[0],
            'station':request[1],
            'location':request[2],
            'channel':request[3],
            'starttime':UTCDateTime(request[4]),
            'endtime':UTCDateTime(request[5])
        }
        # issue here if any of these array values are too long (probably station list)
        # if so, break them apart
        if len(request[1]) > 24:  # Assuming station is the field that might be too long
            st = obspy.Stream()
            split_stations = request[1].split(',')
            for s in split_stations:
                try:
                    st += waveform_clients.get_waveforms(station=s, **{k: v for k, v in kwargs.items() if k != 'station'})
                except Exception as e:
                    print(f"Error fetching data for station {s}: {str(e)}")
        else:
            st = waveform_clients.get_waveforms(**kwargs)

    except Exception as e:
        print(f"Error fetching data ---------------: {request} {str(e)}")
        # >> TODO add failure & denied to database also? will require DB structuring and logging HTTP error response
        return

    # A means to group traces by day to avoid slowdowns with highly fractured data
    traces_by_day = defaultdict(obspy.Stream)
    
    for tr in st:
        net = tr.stats.network
        sta = tr.stats.station
        loc = tr.stats.location
        cha = tr.stats.channel
        starttime = tr.stats.starttime
        endtime = tr.stats.endtime

        # address instances where trace start leaks into previous date
        day_boundary = UTCDateTime(starttime.date + datetime.timedelta(days=1))
        if (day_boundary - starttime) <= tr.stats.delta:
            starttime = day_boundary
        
        current_time = UTCDateTime(starttime.date)
        while current_time < endtime:
            year = current_time.year
            doy = current_time.julday
            
            next_day = current_time + 86400 
            day_end = min(next_day - tr.stats.delta, endtime)
            
            day_tr = tr.slice(current_time, day_end, nearest_sample=True)
            day_key = (year, doy, net, sta, loc, cha)
            traces_by_day[day_key] += day_tr
            
            current_time = next_day
    
    # Process each day's data
    to_insert_db = []
    for (year, doy, net, sta, loc, cha), day_stream in traces_by_day.items():
        full_sds_path = os.path.join(sds_path, str(year), net, sta, f"{cha}.D")
        filename = f"{net}.{sta}.{loc}.{cha}.D.{year}.{doy:03d}"
        full_path = os.path.join(full_sds_path, filename)
        
        os.makedirs(full_sds_path, exist_ok=True)
        
        if os.path.exists(full_path):
            try:
                existing_st = obspy.read(full_path)
            except Exception as e:
                print(f"! Could not read {full_path}: {e}")
                continue
            existing_st += day_stream
            existing_st.merge(method=-1, fill_value=None)
            existing_st._cleanup()
            if existing_st:
                print(f"  merging {full_path}")
        else:
            existing_st = day_stream
            if existing_st:
                print(f"  writing {full_path}")

        existing_st = obspy.Stream([tr for tr in existing_st if len(tr.data) > 0])

        if existing_st:
            try:
                existing_st.write(full_path, format="MSEED", encoding='STEIM2') #MSEED/STEIM2 are normal but users may want to change these... someday
                to_insert_db.append(stream_to_db_element(existing_st))
            except Exception as e:
                print(f"! Could not write {full_path}: {e}")
    # Update database
    try:
        num_inserted = db_manager.bulk_insert_archive_data(to_insert_db)
    except Exception as e:
        print("! Error with bulk_insert_archive_data: ", e)



# MAIN RUN FUNCTIONS
# ==================================================================
def setup_paths(settings: SeismoLoaderSettings):
    sds_path = settings.sds_path # config['SDS']['sds_path']  <<<<<<<<< should this be settings.sds.sds_path?
    if not sds_path:
        raise ValueError("SDS Path not set!!!")

    # Setup SDS directory
    if not os.path.exists(sds_path):
        os.makedirs(sds_path)

    # Setup database directory
    db_path = settings.db_path # config['DATABASE']['db_path'] <<<<<<< should this be settings.database.db_path?
    if not db_path:
        if not os.path.exists(db_path):
            os.makedirs(db_path)
        db_path = os.path.join(sds_path,"database.sql")

    # Setup database
    #if not os.path.exists(db_path):
    #    setup_database(db_path)

    # Setup database manager (& database if non-existent)
    # ******** is this the best place to do this???
    db_manager = DatabaseManager(db_path)

    settings.sds_path = sds_path
    settings.db_path  = db_path

    return settings, db_manager


## ***use ObsPy for the below functions
from obspy.geodetics import kilometer2degrees, degrees2kilometers

def convert_radius_to_degrees(radius_meters):
    #Convert radius from meters to degrees.
    kilometers = radius_meters / 1000
    degrees = kilometers / 111.32
    return degrees

def convert_degress_to_radius_km(radius_degree):
    return radius_degree * 111.32

def convert_degrees_to_radius_meter(radius_degree):
    return convert_degress_to_radius_km(radius_degree) * 1000


def get_stations(settings: SeismoLoaderSettings):
    """
    Refine input args to what is needed for get_stations
    """
    print("Running get_stations") #debug for now

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client.value)
    if settings.station and settings.station.client: # config['STATION']['client']:
        station_client = Client(settings.station.client.value) # Client(config['STATION']['client'])
    else:
        station_client = waveform_client

    net = settings.station.network
    if not net:
        net = '*'
    sta = settings.station.station
    if not sta:
        sta = '*'
    loc = settings.station.location
    if not loc:
        loc = '*'
    cha = settings.station.channel
    if not cha:
        cha = '*'

    kwargs = {
        'network': net,
        'station': sta,
        'location': loc,
        'channel': cha,
        'starttime': starttime,
        'endtime': endtime,
        'includerestricted': settings.station.include_restricted,
        'level': settings.station.level.value
    }

    # check station_client compatibility
    if 'station' not in station_client.services.keys():
        print("Station service not available at %s, no stations returned" % station_client.base_url)
        return None
    for key in kwargs.keys():
        if key not in station_client.services['station'].keys():
            del kwargs[key]

    inv = None
    inventory = settings.station.local_inventory
    if inventory:
        # User has specified this specific pre-existing (filepath) inventory to use
        inv = obspy.read_inventory(inventory)

    elif (not inventory and settings.station.geo_constraint):
        for geo in settings.station.geo_constraint:
            if geo.geo_type == GeoConstraintType.BOUNDING:
                ## TODO Test if all variables exist / error if not
                curr_inv = station_client.get_stations(
                    minlatitude =geo.coords.min_lat,
                    maxlatitude =geo.coords.max_lat,
                    minlongitude=geo.coords.min_lng,
                    maxlongitude=geo.coords.max_lng,
                    **kwargs
                )
            elif geo.geo_type == GeoConstraintType.CIRCLE:
                ## TODO Test if all variables exist / error if not
                curr_inv = station_client.get_stations(
                    minradius=geo.coords.min_radius,
                    maxradius=geo.coords.max_radius,
                    latitude=geo.coords.lat,
                    longitude=geo.coords.lng,
                    **kwargs
                )
            else:
                print(f"Unknown Geometry type: {geo.geo_type}")

            if inv:
                inv += curr_inv
            else:
                inv = curr_inv
    else: # No geographic constraint, search via inventory alone
        inv = station_client.get_stations(**kwargs)

    # Remove unwanted stations or networks
    if settings.station.exclude_stations: # config['STATION']['exclude_stations']:
        # exclude_list = config['STATION']['exclude_stations'].split(',') #format is NN.STA
        for ns in settings.station.exclude_stations:
            n,s = ns.upper().split('.') #this is necessary as format is n.s
            inv = inv.remove(network=n,station=s)

    # Add anything else we were told to
    if settings.station.force_stations: # config['STATION']['force_stations']:
        # add_list = config['STATION']['force_stations'].split(',') #format is NN.STA
        for ns in settings.station.force_stations:
            n,s = ns.upper().split('.')
            try:
                inv += station_client.get_stations(
                    network=n,
                    station=s,
                    location='*',
                    channel='[FGDCESHBML][HN]?',
                    level=settings.station.level.value
                )
            except:
                print("Could not find requested station %s at %s" % (f"{n}.{s}",settings.station.client.value))
                continue

    return inv


def get_events(settings: SeismoLoaderSettings) -> List[Catalog]:

    print("Running get_events") #debug for now

    starttime = UTCDateTime(settings.event.date_config.start_time)
    endtime = UTCDateTime(settings.event.date_config.end_time)

    waveform_client = Client(settings.waveform.client.value)
    if settings.event and settings.event.client:
        event_client = Client(settings.event.client.value)
    else:
        event_client = waveform_client

    if settings.event.local_catalog:
        try:
            return obspy.read_events(settings.event.local_catalog)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {settings.event.local_catalog}")
        except PermissionError:
            raise PermissionError(f"Permission denied for accessing the file: {settings.event.local_catalog}")
        except Exception as e:
            raise Exception(f"An unexpected error occurred: {e}")

    catalog = Catalog(events=None)

    # todo add more e.g. catalog, contributor
    kwargs = {
        'starttime':starttime,
        'endtime':endtime,
        'minmagnitude':settings.event.min_magnitude,
        'maxmagnitude':settings.event.max_magnitude,
        'mindepth':settings.event.min_depth,
        'maxdepth':settings.event.max_depth,
        'includeallorigins':settings.event.include_all_origins,
        'includeallmagnitudes':settings.event.include_all_magnitudes,
        'includearrivals':settings.event.include_arrivals,
    }

    # check event_client for compatibility
    if 'event' not in event_client.services.keys():
        print("Event service not available at %s, no events returned" % event_client.base_url)
        return catalog
    for key in kwargs.keys():
        if key not in event_client.services['event'].keys():
            del kwargs[key]

    if len(settings.event.geo_constraint) == 0:
        try:
            cat = event_client.get_events(
                **kwargs
            )
            print("Global Search of Events. Found %d events from %s" % (len(cat),settings.event.client.value))
            catalog.extend(cat)
        except:
            print("No events found!") #TODO elaborate
        
        return catalog

    for geo in settings.event.geo_constraint:
        if geo.geo_type == GeoConstraintType.CIRCLE:
            try:
                cat = event_client.get_events(
                    latitude = geo.coords.lat,
                    longitude= geo.coords.lng,
                    minradius= geo.coords.min_radius,
                    maxradius= geo.coords.max_radius,
                    **kwargs
                )
                print("Found %d events from %s" % (len(cat),settings.event.client.value))
                catalog.extend(cat)
            except:
                print("No events found!") #TODO elaborate
                
        elif geo.geo_type == GeoConstraintType.BOUNDING:
            try:
                cat = event_client.get_events(
                    minlatitude  = geo.coords.min_lat,
                    minlongitude = geo.coords.min_lng,
                    maxlatitude  = geo.coords.max_lat,
                    maxlongitude = geo.coords.max_lng,
                    **kwargs
                )
                print("Found %d events from %s" % (len(cat),settings.event.client.value))
                catalog.extend(cat)
            except:
                print("No events found!") #TODO elaborate
        else:
            # FIXME: Once concluded on Geo Type, fix below terms: radial and box
            raise ValueError("Event search type: %s is invalid. Must be 'radial' or 'box'" % geo.geo_type.value)
    
    return catalog


def run_continuous(settings: SeismoLoaderSettings):
    """
    Retrieves continuous seismic data over long time intervals for a set of stations
    defined by the `inv` parameter. The function manages multiple steps including
    generating data requests, pruning unnecessary requests based on existing data,
    combining requests for efficiency, and finally archiving the retrieved data.

    The function uses a client setup based on the configuration in `settings` to
    handle different data sources and authentication methods. Errors during client
    creation or data retrieval are handled gracefully, with issues logged to the console.

    Parameters:
    - settings (SeismoLoaderSettings): Configuration settings containing client information,
      authentication details, and database paths necessary for data retrieval and storage.
      This should include the start and end times for data collection, database path,
      and SDS archive path among other configurations.
    - inv (Inventory): An object representing the network/station/channel inventory
      to be used for data requests. This is usually prepared prior to calling this function.

    Workflow:
    1. Initialize clients for waveform data retrieval.
    2. Retrieve station information based on settings.
    3. Collect initial data requests for the given time interval.
    4. Prune requests based on existing data in the database to avoid redundancy.
    5. Combine similar requests to minimize the number of individual operations.
    6. Update or create clients based on specific network credentials if necessary.
    7. Execute data retrieval requests, archive data to disk, and update the database.

    Raises:
    - Exception: General exceptions could be raised due to misconfiguration, unsuccessful
      data retrieval or client initialization errors. These exceptions are caught and logged,
      but not re-raised, allowing the process to continue with other requests.

    Notes:
    - It is crucial to ensure that the settings object is correctly configured, especially
      the client details and authentication credentials to avoid runtime errors.
    - The function logs detailed information about the processing steps and errors to aid
      in debugging and monitoring of data retrieval processes.
    """
    settings, db_manager = setup_paths(settings)

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client.value) # note we may have three different clients here: waveform, station, and event. be careful to keep track

    # Collect requests
    requests = collect_requests(settings.station.selected_invs,starttime,endtime,
        days_per_request=settings.waveform.days_per_request)

    # Remove any for data we already have (requires updated db)
    pruned_requests= prune_requests(requests, db_manager)

    # Break if nothing to do
    if len(pruned_requests) < 1:
        return

    # Combine these into fewer (but larger) requests
    combined_requests = combine_requests(pruned_requests)

    waveform_clients= {'open':waveform_client}
    requested_networks = [ele[0] for ele in combined_requests]

    ######## lets double check this.. not sure if it will follow NN.SSSS as well as NN
    for cred in settings.auths:
        if cred.nslc_code not in requested_networks:
            continue
        try:
            new_client = Client(settings.waveform.client,user=cred.username,password=cred.password)
        except:
            print("Issue creating client: %s %s via %s:%s" % (settings.waveform.client,cred.nslc_code,cred.username,cred.password))
            continue
        waveform_clients.update({cred.nslc_code:new_client})

    # Archive to disk and updated database
    for request in combined_requests:
        print(request)
        time.sleep(0.05) #to help ctrl-C out if needed
        try: 
            archive_request(request, waveform_clients, settings.sds_path, db_manager) # think should this be waveform_clientS plural ?
        except Exception as e:
            print("Continuous request not successful: ",request, " with exception: ", e)

    # Goint through all original requests //// ** not sure what this does from here on
    time_series = []
    for req in requests:
        data = pd.DataFrame()
        query = SeismoQuery(
            network = req[0],
            station = req[1],
            location = req[2],
            channel = req[3],
            starttime = req[4],
            endtime = req[5]
        )
        try:
            data = stream_to_dataframe(get_local_waveform(query, settings))
        except Exception as e:
            print(str(e))
        
        time_series.append({
            'Network': query.network,
            'Station': query.station,
            'Location': query.location,
            'Channel': query.channel,
            'Data': data
        })

    return time_series



def run_event(settings: SeismoLoaderSettings):
    """
    Processes and downloads seismic event data for each event in the provided catalog using the specified
    settings and station inventory. The function handles data requests, filters out already available data,
    combines requests for efficiency, and manages authentication for access to restricted data.

    Parameters:
    - settings (SeismoLoaderSettings): Configuration settings that include client details, authentication credentials,
      event-specific parameters like radius and time window, and paths for data storage.
    - inv (Inventory): The network/station/channel inventory to be used for data requests, typically relevant to the
      stations involved in the seismic events.
    - catalog (Catalog): A collection of seismic events, each containing data like origin time, coordinates, and depth.

    Workflow:
    1. Initialize a primary waveform client for data retrieval.
    2. Loop through each event in the catalog, collecting necessary data request parameters.
    3. For each event, collect data requests based on its geographical and temporal parameters.
    4. Filter out data requests that are already satisfied with existing data in the database.
    5. Optionally combine requests for operational efficiency.
    6. Manage additional client creation for restricted data based on user credentials.
    7. Execute the data retrieval requests, then archive the data to disk and update the database.

    Raises:
    - Exception: General exceptions could be caught related to client creation, data retrieval, or during the
      archival process. These are logged but not re-raised, allowing the function to continue processing further events.

    Notes:
    - The function includes comments questioning the design, such as the redundancy of using 'inv' from STATION
      settings in EVENTS processing, which suggests a potential refactor for better separation of concerns or efficiency.
    - Care should be taken when modifying settings and handling authentication to ensure the integrity and security
      of data access and retrieval.
    """
    settings, db_manager = setup_paths(settings)

    waveform_client = Client(settings.waveform.client.value)
    
    try:
        ttmodel = TauPyModel(settings.event.model)
    except Exception as e:
        print("Issue loading TauPyModel ",settings.event.model, e, "defaulting to IASP91")
        ttmodel = TauPyModel('IASP91')

    # @FIXME: Below line seems to be redundant as in above lines, event_client was set.
    # event_client = Client(config['EVENT']['client'])

    # minradius = settings.event.min_radius # float(config['EVENT']['minradius'])
    # maxradius = settings.event.max_radius # float(config['EVENT']['maxradius'])

    #now loop through events
    # NOTE: Why "inv" collections from STATION block is included in EVENTS?
    #       Isn't it the STATIONS have their own searching settings?
    #       If the search settings such as map search and time search are the
    #       same, why separate parameters are defined for events?
    for i,eq in enumerate(settings.event.selected_catalogs):
        print("--> Downloading event (%d/%d) %s (%.4f lat %.4f lon %.1f km dep) ...\n" % (i+1,len(settings.event.selected_catalogs),
            eq.origins[0].time,eq.origins[0].latitude,eq.origins[0].longitude,eq.origins[0].depth/1000))

        # Collect requests
        requests,new_arrivals,p_arrivals = collect_requests_event(
            eq, settings.station.selected_invs,
            model=ttmodel,
            settings=settings
        )

        # Import any new arrival info into our database
        if new_arrivals:
            db_manager.bulk_insert_arrival_data(new_arrivals)
            print(" ~ %d new arrivals added to database" % len(new_arrivals))        
        # Remove any for data we already have (requires db be updated)
        pruned_requests= prune_requests(requests, db_manager)

        if len(pruned_requests) < 1:
            print("--> Event already downloaded (%d/%d) %s (%.4f lat %.4f lon %.1f km depth) ...\n" % (i+1,len(settings.event.selected_catalogs),
            eq.origins[0].time,eq.origins[0].latitude,eq.origins[0].longitude,eq.origins[0].depth/1000))
            continue

        # Combine these into fewer (but larger) requests
        # this probably makes little for sense EVENTS, but its inexpensive and good for testing purposes
        combined_requests = combine_requests(pruned_requests)

        # Add additional clients if user is requesting any restricted data
        waveform_clients= {'open':waveform_client}
        requested_networks = [ele[0] for ele in combined_requests]

        ## may have to review this part va line 1264 seedfault.0.40.py
        for cred in settings.auths:
            if cred.nslc_code not in requested_networks:
                continue
            try:
                new_client = Client(settings.waveform.client,user=cred.username,password=cred.password)
            except:
                print("Issue creating client: %s %s via %s:%s" % (settings.waveform.client,cred.nslc_code,cred.username,cred.password))
                continue
            waveform_clients.update({cred.nslc_code:new_client})

        # Archive to disk and update database
        for request in combined_requests:
            time.sleep(0.05) #to help ctrl-C out if needed
            print(request)
            try: 
                archive_request(request,waveform_client,settings.sds_path,db_manager)
            except Exception as e:
                print("Event request not successful: ",request, str(e))
        
        ### unsure what below does
        time_series = []
        for req in requests:
            data = pd.DataFrame()
            query = SeismoQuery(
                network = req[0],
                station = req[1],
                location = req[2],
                channel = req[3],
                starttime = req[4],
                endtime = req[5]
            )
            try:
                data = stream_to_dataframe(get_local_waveform(query, settings))
            except Exception as e:
                print(str(e))
            
            # Get P arrival time for this waveform
            station_id = f"{query.network}.{query.station}"
            p_arrival = p_arrivals.get(station_id)
            time_series.append({
                'Network': query.network,
                'Station': query.station,
                'Location': query.location,
                'Channel': query.channel,
                'Data': data,
                'P_Arrival': p_arrival
            })
        
        return time_series



def run_main(settings: SeismoLoaderSettings = None, from_file=None):
    if not settings and from_file:
        settings = SeismoLoaderSettings()
        settings = settings.from_cfg_file(cfg_path = from_file)

    settings, db_manager = setup_paths(settings)

    download_type = settings.download_type.value
    if not is_in_enum(download_type, DownloadType):
        download_type = DownloadType.CONTINUOUS

    if download_type == DownloadType.CONTINUOUS:
        settings.station.selected_invs = get_stations(settings)
        run_continuous(settings)

    if download_type == DownloadType.EVENT:
        settings.event.selected_catalogs = get_events(settings)
        settings.station.selected_invs   = get_stations(settings)
        run_event(settings)

    # Now we can optionally clean up our database (stich continous segments, etc)
    print("\n ~~ Cleaning up database ~~")
    db_manager.join_continuous_segments(settings.proccess.gap_tolerance)



################ end function declarations, start program
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 seismoloader.py input.cfg")
        sys.exit(1)
    
    config_file = sys.argv[1]

    try:
        run_main(from_file=config_file)
    except Exception as e:
        print(f"Error occured while running: {str(e)}")
        raise e

    

