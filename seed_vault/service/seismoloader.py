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
## NOT USED ANYMORE from tabulate import tabulate # non-standard. this is just to display the db contents
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
from seed_vault.service.waveform import get_local_waveform, stream_to_dataframe
from obspy.clients.fdsn.header import URL_MAPPINGS, FDSNNoDataException

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

            if section.upper() in ['AUTH','DATABASE','SDS','WAVEFORM']:
                processed_key = key
                processed_value = value if value is not None else None
            else:
                # Convert to lowercase for other sections
                processed_key = key.lower()
                processed_value = value.lower() if value is not None else None
            
            processed_config.set(section, processed_key, processed_value)

    return processed_config


def to_timestamp(time_obj):
    """ Anything to timestamp helper. """
    if isinstance(time_obj, (int, float)):
        return float(time_obj)
    elif isinstance(time_obj, datetime):
        return time_obj.timestamp()
    elif isinstance(time_obj, UTCDateTime):
        return time_obj.timestamp
    else:
        raise ValueError(f"Unsupported time type: {type(time_obj)}")


def miniseed_to_db_element(file_path):
    """ Create a database element from a miniseed file. """
    if not os.path.isfile(file_path):
        return None
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
    """ Create a database element from a stream 
    (assuming all traces have same NSLC!)
    just a bit faster than re-opening the file 
    again via miniseed_to_db_element. """

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
    newer_than=None, num_processes=None, gap_tolerance = 60):

    """ Utility function to populate the archive_table in our database. """

    db_manager = DatabaseManager(db_path)

    # Set to possibly the maximum number of CPUs!
    if num_processes is None or num_processes <= 0:
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

    db_manager.join_continuous_segments(gap_tolerance)


## maybe this simple version is fine enough... 
def populate_database_from_files_dumb(cursor, file_paths=[]):
    """ Quickly insert/update a few SDS archive files into the SQL database. Assume cursor already open! """
    now = int(datetime.datetime.now().timestamp())
    for fp in file_paths:
        result  = miniseed_to_db_element(fp)
        if result:
            result = result + (now,)
            cursor.execute('''
                INSERT OR REPLACE INTO archive_data
                (network, station, location, channel, starttime, endtime, importtime)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', result)


def populate_database_from_files(cursor, file_paths=[]):
    """ Quickly insert/update a few SDS archive files into the SQL database. """
    now = int(datetime.datetime.now().timestamp())
    for fp in file_paths:
        result = miniseed_to_db_element(fp)
        if result:
            network, station, location, channel, start_timestamp, end_timestamp = result
            
            # First check for existing overlapping spans
            cursor.execute('''
                SELECT starttime, endtime FROM archive_data
                WHERE network = ? AND station = ? AND location = ? AND channel = ?
                AND NOT (endtime < ? OR starttime > ?)
            ''', (network, station, location, channel, start_timestamp, end_timestamp))
            
            overlaps = cursor.fetchall()
            if overlaps:
                # Merge with existing spans
                start_timestamp = min(start_timestamp, min(row[0] for row in overlaps))
                end_timestamp = max(end_timestamp, max(row[1] for row in overlaps))
                
                # Delete overlapping spans
                cursor.execute('''
                    DELETE FROM archive_data
                    WHERE network = ? AND station = ? AND location = ? AND channel = ?
                    AND NOT (endtime < ? OR starttime > ?)
                ''', (network, station, location, channel, start_timestamp, end_timestamp))
            
            # Insert the new or merged span
            cursor.execute('''
                INSERT INTO archive_data
                (network, station, location, channel, starttime, endtime, importtime)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (network, station, location, channel, start_timestamp, end_timestamp, now))


# Requests for Continuous Data
def collect_requests(inv, time0, time1, days_per_request=3):
    """ Collect all requests required to download everything in inventory, split into X-day periods. """
    requests = []  # network, station, location, channel, starttime, endtime

    # Sanity check request times
    time1 = min(time1, UTCDateTime.now()-120)
    if time0 >= time1:
        return None
    
    for net in inv:
        for sta in net:
            for cha in sta:
                start_date = max(time0, cha.start_date.date)
                if cha.end_date:
                    end_date = min(time1 - (1/cha.sample_rate),cha.end_date.date + datetime.timedelta(days=1))
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
    """ Get first P/S arrivals given an earthquake object, distance, and traveltime model. """

    eq_time = eq.origins[0].time
    eq_depth = eq.origins[0].depth / 1000  # depths are in meters for QuakeML

    try:
        phasearrivals = ttmodel.get_travel_times(
            source_depth_in_km=eq_depth,
            distance_in_degree=dist_deg,
            phase_list=['ttbasic']
        )
    except Exception as e:
        print(f"Error calculating travel times: {str(e)}")
        return None, None

    p_arrival_time = None
    s_arrival_time = None
    # "P" is whatever the first arrival is.. not necessarily literally uppercase P
    if phasearrivals[0]:
        p_arrival_time = eq_time + phasearrivals[0].time

    # Now get "S"...
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


### probably cut this function entirely for now
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


def collect_requests_event(eq,inv,min_dist_deg=30,max_dist_deg=90,
                           before_p_sec=20,after_p_sec=160,
                           model=None,settings=None,highest_sr_only=True):
    """ Collect requests for event eq for stations in inv. """
    settings, db_manager = setup_paths(settings)
    origin = eq.origins[0] # defaulting to preferred origin
    ot = origin.time
    
    if highest_sr_only:
        sub_inv = select_highest_samplerate(inv,time=ot,minSR=5) #filter by time and also select highest samplerate
    else:
        sub_inv = inv.select(time = ot) #only filter by time
    before_p_sec = settings.event.before_p_sec
    after_p_sec = settings.event.after_p_sec

    # Failsafe to ensure a model is loaded
    if not model:
        model = TauPyModel('IASP91')

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
                               net.code,sta.code) #TODO also check models are consistent? not critical..
            if fetched_arrivals:
                p_time,s_time = fetched_arrivals # timestamps
                t_start = p_time - abs(before_p_sec)
                t_end = p_time + abs(after_p_sec)
                # Add the already-fetched arrivals to our dictionary
                p_arrivals[f"{net.code}.{sta.code}"] = p_time
            else:
                dist_deg = locations2degrees(origin.latitude,origin.longitude,\
                                             sta.latitude,sta.longitude)
                dist_m,azi,backazi = gps2dist_azimuth(origin.latitude,origin.longitude,\
                                             sta.latitude,sta.longitude)
                
                p_time, s_time = get_p_s_times(eq,dist_deg,model)
                if p_time is None:
                    print(f"Warning: Unable to calculate any first arrival for {net.code}.{sta.code}. Something seems wrong...")
                    continue

                if s_time is None:
                    s_time_timestamp = None
                else:
                    s_time_timestamp = s_time.timestamp

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
                                    s_time_timestamp,settings.event.model))

            # Add to our requests
            for cha in sta: # TODO will have to had filtered channels prior to this, else will grab them all
                t_end = min(t_end, datetime.datetime.now().timestamp() - 120)
                t_start = min(t_start,t_end)
                requests_per_eq.append((
                    net.code,
                    sta.code,
                    cha.location_code,
                    cha.code,
                    # NEED REVIEW: not sure if this is needed, all times should be assumed UTC
                    datetime.datetime.fromtimestamp(t_start, tz=datetime.timezone.utc).isoformat(),
                    datetime.datetime.fromtimestamp(t_end,   tz=datetime.timezone.utc).isoformat() ))

    return requests_per_eq, arrivals_per_eq, p_arrivals


def combine_requests(requests):
    """ Combine requests for efficiency. """

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

def get_sds_filenames(n, s, l, c, time_start, time_end, sds_path):
    current_time = time_start
    filenames = []
    while current_time <= time_end:
        year = str(current_time.year)
        doy = str(current_time.julday).zfill(3)
        
        path = f"{sds_path}/{year}/{n}/{s}/{c}.D/{n}.{s}.{l}.{c}.D.{year}.{doy}"
        
        filenames.append(path)
        
        current_time += 86400
    
    return filenames


def prune_requests(requests, db_manager, sds_path, min_request_window=3):
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

            # Check if target filenames exist already.. may need to do a quick database update
            existing_filenames = get_sds_filenames(network, station, location, channel, 
                start_time, end_time, sds_path)
            
            # Query the database for existing data
            cursor.execute('''
                SELECT starttime, endtime FROM archive_data
                WHERE network = ? AND station = ? AND location = ? AND channel = ?
                AND endtime >= ? AND starttime <= ?
                ORDER BY starttime
            ''', (network, station, location, channel, start_time.isoformat(), end_time.isoformat()))
            
            existing_data = cursor.fetchall()


            # If SDS filenames are there, but database is empty.. need to update db before continuing
            if existing_filenames and len(existing_data) < len(existing_filenames):
                populate_database_from_files(cursor, file_paths=existing_filenames)
                
                # RE-Query the newly-updated database
                cursor.execute('''
                    SELECT starttime, endtime FROM archive_data
                    WHERE network = ? AND station = ? AND location = ? AND channel = ?
                    AND endtime >= ? AND starttime <= ?
                    ORDER BY starttime
                ''', (network, station, location, channel, start_time.isoformat(), end_time.isoformat()))
                
                existing_data = cursor.fetchall()
            
            if not existing_data and not existing_filenames:
                # If no evidence we have this data already, keep the entire request
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
        time0 = time.time()
        if request[0] in waveform_clients.keys():  # Per-network authentication
            wc = waveform_clients[request[0]]
        elif request[0]+'.'+request[1] in waveform_clients.keys():  # Per-station e.g. NN.SSSSS (not currently working TODO)
            wc = waveform_clients[request[0]+'.'+request[1]]
        else:
            wc = waveform_clients['open']

        kwargs = {
            'network':request[0].upper(),
            'station':request[1].upper(),
            'location':request[2].upper(),
            'channel':request[3].upper(),
            'starttime':UTCDateTime(request[4]),
            'endtime':UTCDateTime(request[5])
        }

        # If the request is too long, break it apart 
        if len(request[1]) > 24:  # Assuming station is the field that might be too long
            st = obspy.Stream()
            split_stations = request[1].split(',')
            for s in split_stations:
                try:
                    st += wc.get_waveforms(station=s, **{k: v for k, v in kwargs.items() if k != 'station'})
                except Exception as e:
                    print(f"Error fetching data for station {s}: {str(e)}")
        else:
            st = wc.get_waveforms(**kwargs)

        # Download info
        download_time = time.time() - time0
        download_size = sum(tr.data.nbytes for tr in st)/1024**2 # MB
        print(f"      Downloaded {download_size:.2f} MB @ {download_size/download_time:.2f} MB/s")    

    except Exception as e:
        print(f" Error fetching data ---------------: {request} {str(e)}")
        # TODO add failure & denied to database also? will require DB structuring and logging HTTP error response
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

        # Address instances where trace start leaks into previous date
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
            existing_st._cleanup(misalignment_threshold=0.25)
            if existing_st:
                print(f"  ... Merging {full_path}")
        else:
            existing_st = day_stream
            if existing_st:
                print(f"  ... Writing {full_path}")

        existing_st = obspy.Stream([tr for tr in existing_st if len(tr.data) > 0])

        if existing_st:
            try:
                existing_st.write(full_path, format="MSEED", encoding='STEIM2') # MSEED/STEIM2 are very sensible defaults
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
    sds_path = settings.sds_path
    if not sds_path:
        raise ValueError("SDS Path not set!!!")

    # Setup SDS directory
    if not os.path.exists(sds_path):
        os.makedirs(sds_path)

    # Setup database directory
    db_path = settings.db_path

    # Setup database manager (& database if non-existent)
    db_manager = DatabaseManager(db_path)

    settings.sds_path = sds_path
    settings.db_path  = db_path

    return settings, db_manager


## TODO TODO  ***use ObsPy for the below functions
from obspy.geodetics import kilometer2degrees, degrees2kilometers

def convert_radius_to_degrees(radius_meters):
    # Convert radius from meters to degrees.
    kilometers = radius_meters / 1000
    degrees = kilometers / 111.32
    return degrees

def convert_degress_to_radius_km(radius_degree):
    return radius_degree * 111.32

def convert_degrees_to_radius_meter(radius_degree):
    return convert_degress_to_radius_km(radius_degree) * 1000

def get_selected_stations_at_channel_level(settings: SeismoLoaderSettings):
    
    print("Running get_selected_stations_at_channel_level")
    
    waveform_client = Client(settings.waveform.client)
    if settings.station and settings.station.client:
        station_client = Client(settings.station.client)
    else:
        station_client = waveform_client

    invs = Inventory()
    for network in settings.station.selected_invs:
        for station in network:
            try:
                updated_inventory = station_client.get_stations(
                    network=network.code,
                    station=station.code,
                    level="channel"
                ) ### it will be faster to also filter start/end times here (review needed)
                
                invs += updated_inventory
                
            except Exception as e:
                print(f"Error updating station {station.code}: {e}")

    settings.station.selected_invs = invs

    return settings


def get_stations(settings: SeismoLoaderSettings):
    """ Refine input args to what is needed for get_stations. """
    print("Running get_stations")

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client)
    if settings.station and settings.station.client:
        station_client = Client(settings.station.client)
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

    # Remove kwargs keys not in station_client
    new_kwargs = kwargs.copy()
    for key in kwargs.keys():
        if key not in station_client.services['station'].keys():
            del new_kwargs[key]
    kwargs = new_kwargs

    inv = None
    inventory = settings.station.local_inventory
    if inventory:
        # User has specified this specific pre-existing (filepath) inventory to use
        inv = obspy.read_inventory(inventory,level='channel')

    elif (not inventory and settings.station.geo_constraint):
        for geo in settings.station.geo_constraint:
            curr_inv = None
            try:
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
            except FDSNNoDataException:
                print(f"No stations found in {station_client.base_url} with given geographic bounds")
                pass

            if curr_inv is not None:
                if inv:
                    inv += curr_inv
                else:
                    inv = curr_inv

    else: # No geographic constraint, search via inventory alone
        try:
            inv = station_client.get_stations(**kwargs)
        except FDSNNoDataException:
            print(f"No stations found in {station_client.base_url} with given parameters")
            return None


    # Remove unwanted stations or networks
    if settings.station.exclude_stations:
        # exclude_list = config['STATION']['exclude_stations'].split(',') #format is NN.STA
        for ns in settings.station.exclude_stations:
            n,s = ns.upper().split('.') #this is necessary as format is n.s
            inv = inv.remove(network=n,station=s)

    # Add anything else we were told to
    if settings.station.force_stations: 
        # add_list = config['STATION']['force_stations'].split(',') #format is NN.STA
        for ns in settings.station.force_stations:
            n,s = ns.upper().split('.')
            try:
                inv += station_client.get_stations(
                    network=n,
                    station=s,
                    location='*', # may be an issue... should probably follow the location filter NEEDS REVIEW
                    channel='[FGDCESHBML][HN]?', # we are somewhat dangerously assuming that seismic data follows conventional channel naming... think it's OK though
                    level=settings.station.level.value
                )
            except:
                print("Could not find requested station %s at %s" % (f"{n}.{s}",settings.station.client))
                continue

    return inv


def get_events(settings: SeismoLoaderSettings) -> List[Catalog]:

    print("Running get_events")

    starttime = UTCDateTime(settings.event.date_config.start_time)
    endtime = UTCDateTime(settings.event.date_config.end_time)

    waveform_client = Client(settings.waveform.client)
    if settings.event and settings.event.client:
        event_client = Client(settings.event.client)
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

    # TODO add more e.g. catalog, contributor
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

    # Check event_client for compatibility
    if 'event' not in event_client.services.keys():
        print("Event service not available at %s, no events returned" % event_client.base_url)
        return catalog

    # Remove kwargs entries not in event_client
    new_kwargs = kwargs.copy()
    for key in kwargs.keys():
        if key not in event_client.services['event'].keys():
            del new_kwargs[key]
    kwargs = new_kwargs

    if len(settings.event.geo_constraint) == 0:
        try:
            cat = event_client.get_events(
                **kwargs
            )
            print("Global Search of Events. Found %d events from %s" % (len(cat),settings.event.client))
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
                print("Found %d events from %s" % (len(cat),settings.event.client))
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
                print("Found %d events from %s" % (len(cat),settings.event.client))
                catalog.extend(cat)
            except:
                print("No events found!") #TODO elaborate
                return catalog
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
    print("Running run_continuous")
    
    settings, db_manager = setup_paths(settings)

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client)

    # Sanity check times
    endtime = min(endtime, UTCDateTime.now()-120)
    if starttime >= endtime:
        print("Starttime greater than than endtime!")
        return

    # Collect requests
    requests = collect_requests(settings.station.selected_invs, 
        starttime, endtime, days_per_request=settings.waveform.days_per_request)

    # Remove any for data we already have (requires updated db)
    pruned_requests= prune_requests(requests, db_manager, settings.sds_path)

    # Break if nothing to do
    if len(pruned_requests) < 1:
        return

    # Combine these into fewer (but larger) requests
    combined_requests = combine_requests(pruned_requests)

    waveform_clients= {'open':waveform_client} #now a dictionary
    requested_networks = [ele[0] for ele in combined_requests]

    # May only work for network-wide credentials at the moment (99% use case)
    for cred in settings.auths:
        cred_net = cred.nslc_code.split('.')[0].upper()
        if cred_net not in requested_networks:
            continue
        try:
            new_client = Client(settings.waveform.client, 
                user=cred.username.upper(), password=cred.password)
            waveform_clients.update({cred_net:new_client})
        except:
            print("Issue creating client: %s %s via %s:%s" % (settings.waveform.client, 
                cred.nslc_code, cred.username, cred.password))
            continue

    # Archive to disk and updated database
    for request in combined_requests:
        print("\n Requesting: ", request)
        time.sleep(0.05) #to help ctrl-C out if needed
        try:
            archive_request(request, waveform_clients, settings.sds_path, db_manager)
        except Exception as e:
            print("Continuous request not successful: ",request, " with exception: ", e)
            continue

    # Goint through all original requests
    time_series = []
    for req in requests:
        data = pd.DataFrame()
        query = SeismoQuery(
            network = req[0].upper(),
            station = req[1].upper(),
            location = req[2].upper(),
            channel = req[3].upper(),
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
    print("Running run_event")
    
    settings, db_manager = setup_paths(settings)

    waveform_client = Client(settings.waveform.client)
    
    try:
        ttmodel = TauPyModel(settings.event.model)
    except Exception as e:
        ttmodel = TauPyModel('IASP91')
    event_streams = []

    for i, eq in enumerate(settings.event.selected_catalogs):
        # Collect requests
        requests, new_arrivals, p_arrivals = collect_requests_event(
            eq, settings.station.selected_invs,
            model=ttmodel,
            settings=settings
        )

        # Import any new arrival info into database
        if new_arrivals:
            db_manager.bulk_insert_arrival_data(new_arrivals)

        # Remove requests for data we already have
        pruned_requests = prune_requests(requests, db_manager)

        # Process new data if needed
        if pruned_requests:
            combined_requests = combine_requests(pruned_requests)
            
            # Setup clients for restricted data
            waveform_clients = {'open': waveform_client}
            requested_networks = [ele[0] for ele in combined_requests]
            
            for cred in settings.auths:
                cred_net = cred.nslc_code.split('.')[0].upper()
                if cred_net not in requested_networks:
                    continue
                try:
                    new_client = Client(settings.waveform.client, 
                                     user=cred.username.upper(),
                                     password=cred.password)
                    waveform_clients.update({cred_net: new_client})
                except Exception as e:
                    print(f"Issue creating client for {cred_net}: {str(e)}")

            # Archive new data
            for request in combined_requests:
                try:
                    archive_request(request, waveform_clients, settings.sds_path, db_manager)
                except Exception as e:
                    print(f"Error archiving request {request}: {str(e)}")

        # Now read all data for this event using get_local_waveform
        event_stream = obspy.Stream()
        for req in requests:  # Use original requests to get all data
            query = SeismoQuery(
                network=req[0],
                station=req[1],
                location=req[2],
                channel=req[3],
                starttime=req[4],
                endtime=req[5]
            )
            
            try:
                st = get_local_waveform(query, settings)
                if st:
                    # Get arrival information from database
                    arrivals = db_manager.fetch_arrivals_distances(
                        str(eq.preferred_origin_id),
                        query.network,
                        query.station
                    )
                    
                    if arrivals:
                        # Add metadata to each trace
                        for tr in st:
                            tr.stats.event_id = str(eq.resource_id)
                            tr.stats.p_arrival = arrivals[0]
                            tr.stats.s_arrival = arrivals[1]
                            tr.stats.distance_km = arrivals[2]
                            tr.stats.distance_deg = arrivals[3]
                            tr.stats.azimuth = arrivals[4]
                    
                    event_stream += st
            except Exception as e:
                print(f"Error reading data for {query.network}.{query.station}: {str(e)}")
                continue

        if len(event_stream) > 0:
            event_streams.append(event_stream)

    return event_streams

def run_main(settings: SeismoLoaderSettings = None, from_file=None):
    if not settings and from_file:
        settings = SeismoLoaderSettings()
        settings = settings.from_cfg_file(cfg_source = from_file)

    settings, db_manager = setup_paths(settings)

    settings.load_url_mapping()
    URL_MAPPINGS = settings.client_url_mapping

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



# # # # # # # # # # # # # # # # # # #

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 seismoloader.py input.cfg") ### TODO / REVIEW I assume this needs updating to new -cli version
        sys.exit(1)
    
    config_file = sys.argv[1]

    try:
        run_main(from_file=config_file)
    except Exception as e:
        print(f"Error occured while running: {str(e)}")
        raise e
