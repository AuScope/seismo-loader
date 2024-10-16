#!/usr/bin/env python3

# CLI SDS data downloader/archiver/database management, use: $ ./seismoloader.py 

#requirements: obspy, tqdm, tabulate, sqlite3, contexlib

# ver 0.3 04/09/2024
# - add event capability, add example continuous/event cfg files, fix a LOT of bugs, other significant renames/structural changes

# ver 0.2 08/2024
# - first shared edition

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

import obspy
from obspy.clients.fdsn import Client
from obspy.geodetics.base import locations2degrees
from obspy import UTCDateTime
from obspy.taup import TauPyModel
from obspy.core.inventory import Inventory
from obspy.core.event import Catalog

from seismic_data.models.config import SeismoLoaderSettings, SeismoQuery
from seismic_data.enums.config import DownloadType, GeoConstraintType
from seismic_data.service.utils import is_in_enum
from seismic_data.service.db import setup_database, safe_db_connection
from seismic_data.service.waveform import get_local_waveform, stream_to_dataframe

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
            if section == 'AUTH':
                # Preserve case for both key and value in AUTH section
                processed_key = key
                processed_value = value if value is not None else None
            else:
                # Convert to lowercase for other sections
                processed_key = key.lower()
                processed_value = value.lower() if value is not None else None
            
            processed_config.set(section, processed_key, processed_value)

    return processed_config



def process_file(file_path):
    try:
        file = os.path.basename(file_path)
        parts = file.split('.')
        if len(parts) != 7:
            return None  # Skip files that don't match the expected format
        
        network, station, location, channel, _, year, dayfolder = parts
        
        # Read the file to get actual start and end times
        st = obspy.read(file_path, headonly=True)
        
        if len(st) == 0:
            print(f"Warning: No traces found in {file_path}")
            return None
        
        start_time = min(tr.stats.starttime for tr in st)
        end_time = max(tr.stats.endtime for tr in st)
        
        return (network, station, location, channel, start_time.isoformat(), end_time.isoformat())
    
    except Exception as e:
        print(f"Error processing file {file_path}: {str(e)}")
        return None


## TODO add a "files newer than" search filter
## TODO remove data where original SDS files no longer exist?
## this can take a long time for someone with a serious archive already (5TB / 768235 files = ~8-12 hours at 4 cores)
def populate_database_from_sds(sds_path, db_path, num_processes=None):
    if num_processes is None:
        num_processes = multiprocessing.cpu_count()
    
    # Collect all file paths
    file_paths = []
    for root, dirs, files in os.walk(sds_path):
        for file in files:
            file_paths.append(os.path.join(root, file))
    
    total_files = len(file_paths)
    print(f"Found {total_files} files to process.")
    
    # Process files with or without multiprocessing (currently having issues with OSX and undoubtably windows is going to be a bigger problem TODO TODO)
    if num_processes > 1:
        try:
            with multiprocessing.Pool(processes=num_processes) as pool:
                results = list(tqdm(pool.imap(process_file, file_paths), total=total_files, desc="Processing files"))
        except Exception as e:
            print(f"Multiprocessing failed: {str(e)}. Falling back to single-process execution.")
            num_processes = 1
    else:
        results = []
        for fp in tqdm(file_paths, desc="Processing files"):
            results.append(process_file(fp))

    # Filter out None results and insert into database
    with safe_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        inserted = 0
        for result in tqdm(filter(None, results), total=len(results), desc="Inserting into database"):
            cursor.execute('''
                INSERT OR REPLACE INTO archive_data 
                (network, station, location, channel, starttime, endtime)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', result)
            inserted += 1
        
        conn.commit()

    print(f"Processed {total_files} files, inserted {inserted} records into the database.")


def join_continuous_segments(db_path, gap_tolerance=60):
    """
    Join continuous data segments in the database, even across day boundaries.
    
    :param db_path: Path to the SQLite database
    :param gap_tolerance: Maximum allowed gap (in seconds) to still consider segments continuous
    """
    with safe_db_connection(db_path) as conn:
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
        
        conn.commit()
    
    print(f"Joined segments. Deleted {len(to_delete)} rows, updated {len(to_update)} rows.")

def reset_id_counter(db_path, table_name):
    """
    Reset the ID counter for a specified table in the SQLite database.
    
    :param db_path: Path to the SQLite database
    :param table_name: Name of the table whose ID counter should be reset
    """
    with safe_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Get the maximum ID currently in the table
        cursor.execute(f"SELECT MAX(id) FROM {table_name}")
        max_id = cursor.fetchone()[0] or 0
        
        # Reset the SQLite sequence
        cursor.execute(f"UPDATE sqlite_sequence SET seq = {max_id} WHERE name = ?", (table_name,))
        
        # If the table doesn't exist in sqlite_sequence, insert it
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table_name, max_id))
        
        conn.commit()
    
    print(f"Reset ID counter for table '{table_name}' to {max_id}")


def display_database_contents(db_path, limit=100):
    """
    Display the contents of the SQLite database using a safe connection.
    
    :param db_path: Path to the SQLite database file
    :param limit: Number of rows to display (default is 100, use None for all rows)
    """
    with safe_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        for table in tables:
            table_name = table[0]
            print(f"\nContents of table '{table_name}':")
            
            # Get column names
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Fetch data
            if limit is not None:
                cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
            else:
                cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            
            # Display data using tabulate for nice formatting
            print(tabulate(rows, headers=columns, tablefmt="grid"))
            
            # Display total number of rows
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            total_rows = cursor.fetchone()[0]
            print(f"Total number of rows in {table_name}: {total_rows}")


def populate_database_from_sds_old(sds_path, db_path):
    conn = sqlite3(db_path)
    cursor = conn.cursor()
    
    for root, dirs, files in os.walk(sds_path):
        for file in tqdm.tqdm(files):
            try:
                # Parse filename
                parts = file.split('.')
                if len(parts) != 7:
                    continue  # SDS format files are fairly particular... 
                
                network, station, location, channel, datatype, year, dayfolder = parts
                
                file_path = os.path.join(root, file)
                
                # Read the file to get actual start and end times
                st = obspy.read(file_path, headonly=True)
                
                if len(st) == 0:
                    print(f"Warning: No traces found in {file_path}")
                    continue
                
                start_time = min(tr.stats.starttime for tr in st)
                end_time = max(tr.stats.endtime for tr in st)
                
                # Insert into database
                cursor.execute('''
                    INSERT INTO archive_data 
                    (network, station, location, channel, starttime, endtime)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (network, station, location, channel, start_time.isoformat(), end_time.isoformat()))
            
            except Exception as e:
                print(f"Error processing file {file}: {str(e)}")
    
    conn.commit()


# Requests for ~continuous data
def collect_requests(inv, time0, time1, days_per_request=5):
    """ Collect all requests required to download everything in inventory, split into 5-day periods """
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
def get_p_s_times(eq,sta_lat,sta_lon,ttmodel):
    eq_lat = eq.origins[0].latitude
    eq_lon = eq.origins[0].longitude
    eq_depth = eq.origins[0].depth / 1000 # TODO confirm this is in meters
    dist_deg = locations2degrees(sta_lat,sta_lon,eq_lat,eq_lon) # probably already calculated at this stage

    try:
        phasearrivals = ttmodel.get_travel_times(source_depth_in_km=eq_depth,distance_in_degree=dist_deg,phase_list=['ttbasic']) #ttp or "ttbasic" or ttall may want to try S picking eventually
    except:
        try:
            phasearrivals = ttmodel.get_travel_times(source_depth_in_km=0,distance_in_degree=dist_deg,phase_list=['ttbasic']) #possibly depth issue if negetive.. OK we only need to "close" anyway
        except:
            return None,None

    try:
        p_duration = phasearrivals[0].time #seconds it takes for p-wave to reach station
    except: #TODO print enough info to explain why.. many possible reasons!
        p_duration = None

    p_arrival_time = eq.origins[0].time + p_duration
    
    # TBH we aren't really concerned with S arrivals, but while we're here, may as well (TODO future use)
    try:
        s_duration = phasearrivals[1].time
    except:
        s_duration = None

    s_arrival_time = eq.origins[0].time + s_duration

    return p_arrival_time,s_arrival_time

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

def collect_requests_event(eq,inv,min_dist_deg=30,max_dist_deg=90,before_p_sec=10,after_p_sec=120,model=None): #todo add params for before_p, after_p, etc
    """ collect all requests for data in inventory for given event eq """

    # n.b. "eq" is an earthquake object, e.g. one element of the array collected in a "catalog" object

    origin = eq.origins[0] # default to the primary I suppose (possible TODO but don't see why anyone would want anything else)
    ot = origin.time
    sub_inv = inv.select(time = ot) # Loose filter to select only stations that were running during the earthquake start

    # TODO: further filter by selecting best available channels

    requests_per_eq = []
    for net in sub_inv:
        for sta in net:
            dist_deg = locations2degrees(sta.latitude,sta.longitude,origin.latitude,origin.longitude)
            if dist_deg < min_dist_deg or dist_deg > max_dist_deg:
                continue
            p_time, s_time = get_p_s_times(eq,sta.latitude,sta.longitude,model)
            if not p_time: continue # TOTO need error msg also

            t_start = p_time - abs(before_p_sec)
            t_end = p_time + abs(after_p_sec)

            for cha in sta: # TODO will have to had filtered channels prior to this, else will grab them all
                requests_per_eq.append((
                    net.code,
                    sta.code,
                    cha.location_code,
                    cha.code,
                    t_start.isoformat() + "Z",
                    t_end.isoformat() + "Z" ))

    return requests_per_eq


def collect_requests_event_revised(eq,inv,before_p_sec=10,after_p_sec=120,model=None, settings=None): #todo add params for before_p, after_p, etc
    """ 
    @Review: Rob please review this
    
    This method is revised as followings:

    1. No more need for params: `min_dist_deg` and `max_dist_deg`. This function will accept a shortlist of selected 
    events and stations.
    """

    # n.b. "eq" is an earthquake object, e.g. one element of the array collected in a "catalog" object

    origin = eq.origins[0] # default to the primary I suppose (possible TODO but don't see why anyone would want anything else)
    ot = origin.time
    sub_inv = inv.select(time = ot) # Loose filter to select only stations that were running during the earthquake start

    # TODO: further filter by selecting best available channels

    requests_per_eq = []
    for net in sub_inv:
        for sta in net:
            p_time, s_time = get_p_s_times(eq,sta.latitude,sta.longitude,model)
            if not p_time: continue # TOTO need error msg also
            print(f"Calculated prediction: Event {eq.resource_id.id}, Station {net.code}.{sta.code}, P: {p_time}, S: {s_time}")

            settings.add_prediction(eq.resource_id.id, f"{net.code}.{sta.code}", p_time, s_time)
            t_start = p_time - abs(before_p_sec)
            t_end = p_time + abs(after_p_sec)

            for cha in sta: # TODO will have to had filtered channels prior to this, else will grab them all
                requests_per_eq.append((
                    net.code,
                    sta.code,
                    cha.location_code,
                    cha.code,
                    t_start.isoformat() + "Z",
                    t_end.isoformat() + "Z" ))

    return requests_per_eq



from collections import defaultdict
def combine_requests(requests):
    """ Combine requests to 
    1) Minimize how many and 
    2) Not include data already present in our database (unless intentionally overwriting) 
    Requests can be combined for multiple stations/channels by comma separation BHZ,BHN,BHE
    it is possible to also extend the times, but we also don't want the requests to be too large
    so, we'll group by matching time only
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

def prune_requests(requests, db_path, min_request_window=2):
    """
    Remove any overlapping requests where already-archived data (via db_path) may exist 
    If any requests are less than min_request_window seconds, ignore
    """
    pruned_requests = []
    
    with safe_db_connection(db_path) as conn:
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
                        pruned_requests.append((network, station, location, channel, 
                                                current_time.isoformat(), db_start.isoformat()))
                    
                    current_time = max(current_time, db_end)
                
                if current_time < end_time - min_request_window:
                    # There's a gap after the last existing data
                    pruned_requests.append((network, station, location, channel, 
                                            current_time.isoformat(), end_time.isoformat()))
    
    return pruned_requests

def archive_request(request,waveform_client,sds_path,db_path):
    """ Send a request to an FDSN center, parse it, save to archive, and update our database """
    try:
        st = waveform_client.get_waveforms(network=request[0],station=request[1],
                            location=request[2],channel=request[3],
                            starttime=UTCDateTime(request[4]),endtime=UTCDateTime(request[5]))
        # return nslc_code, st
    except Exception as e:
        print(f"Error fetching data: {request} {str(e)}")
        # >> TODO add failure & denied to database also. can grep from HTTP status code (204 = no data, etc)
        return

    #now loop through traces
    for tr in st:
        net = tr.stats.network
        sta = tr.stats.station
        loc = tr.stats.location
        cha = tr.stats.channel
        starttime = tr.stats.starttime
        endtime = tr.stats.endtime

        # Files to insert into database
        to_insert_db = []

        # Generate file paths for each day covered by the trace
        current_time = UTCDateTime(starttime.date)
        while current_time < endtime:
            year = current_time.year
            doy = current_time.julday
            
            # Construct the SDS path and filename
            full_sds_path = os.path.join(sds_path, str(year), net, sta, f"{cha}.D")
            filename = f"{net}.{sta}.{loc}.{cha}.D.{year}.{doy:03d}"
            full_path = os.path.join(full_sds_path, filename)

            # Create directory if it doesn't exist
            os.makedirs(full_sds_path, exist_ok=True)

            # Calculate the end of the current day
            next_day = current_time + 86400 
            day_end = min(next_day - tr.stats.delta, endtime)  # Subtract one sample interval

            # Slice the trace for the current day
            day_tr = tr.slice(current_time, day_end)

            if os.path.exists(full_path):
                # If file exists, read it and merge with new data
                existing_st = obspy.read(full_path)
                existing_st += day_tr
                existing_st.merge(method=-1, fill_value=None)  # Merge, preserving gaps, no other QC
                existing_st._cleanup() # gets rid of any overlaps, sub-sample jitter
                existing_st.write(full_path, format="MSEED", reclen=4096, encoding='STEIM2')
                print("  merging ", full_path)
            else:
                # If file doesn't exist, simply write the new data
                day_tr.write(full_path, format="MSEED", reclen=4096, encoding='STEIM2')
                print("  writing ", full_path)

            current_time = next_day

            to_insert_db.append(process_file(full_path))

        with safe_db_connection(db_path) as conn:
            cursor = conn.cursor()
            for ele in to_insert_db:
                cursor.execute('''
                    INSERT OR REPLACE INTO archive_data 
                    (network, station, location, channel, starttime, endtime)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', ele)
            conn.commit()



# MAIN RUN FUNCTIONS
# ==================================================================
def setup_paths(settings: SeismoLoaderSettings):
    sds_path = settings.sds_path # config['SDS']['sds_path']
    if not sds_path:
        raise ValueError("SDS Path not set!!!")

    db_path = settings.db_path # config['DATABASE']['db_path']
    if not db_path:
        db_path = os.path.join(sds_path,"database.sql")

    #setup SDS directory
    if not os.path.exists(sds_path):
        os.makedirs(sds_path)

    #setup database
    if not os.path.exists(db_path):
        setup_database(db_path)

    settings.sds_path = sds_path
    settings.db_path  = db_path

    return settings

def convert_radius_to_degrees(radius_meters):
    """ Convert radius from meters to degrees. """
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
    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client.value)
    if settings.station and settings.station.client: # config['STATION']['client']:
        station_client = Client(settings.station.client.value) # Client(config['STATION']['client'])
    else:
        station_client = waveform_client

    net = settings.station.network # config['STATION']['network']
    if not net:
        net = '*'
    sta = settings.station.station # config['STATION']['station']
    if not sta:
        sta = '*'
    loc = settings.station.location # config['STATION']['location']
    if not loc:
        loc = '*'
    cha = settings.station.channel # config['STATION']['channel']
    if not cha:
        cha = '*'

    inv = None
    inventory = settings.station.local_inventory
    if inventory: # config['STATION']['inventory']:
        # User has specified this specific pre-existing (filepath) inventory to use
        inv = obspy.read_inventory(inventory)

    elif (not inventory and settings.station.geo_constraint):
        for geo in settings.station.geo_constraint:
            if geo.geo_type == GeoConstraintType.BOUNDING:
                    ## TODO Test if all variables exist / error if not  
                curr_inv = station_client.get_stations(
                    network=net,station=sta,
                    location=loc,channel=cha,
                    starttime=starttime,endtime=endtime,
                    minlatitude =geo.coords.min_lat, # float(config['STATION']['minlatitude']),
                    maxlatitude =geo.coords.max_lat,
                    minlongitude=geo.coords.min_lng,
                    maxlongitude=geo.coords.max_lng,
                    includerestricted= settings.station.include_restricted, # config['STATION']['includerestricted'],
                    level=settings.station.level.value
                )
            elif geo.geo_type == GeoConstraintType.CIRCLE:
                ## TODO Test if all variables exist / error if not
                curr_inv = station_client.get_stations(
                    network=net,station=sta,
                    location=loc,channel=cha,
                    starttime=starttime,endtime=endtime,
                    latitude = geo.coords.lat, # float(config['STATION']['latitude']),
                    longitude= geo.coords.lng, # float(config['STATION']['longitude']),
                    # minradius=convert_radius_to_degrees(geo.coords.min_radius), # float(config['STATION']['minradius']),
                    # maxradius=convert_radius_to_degrees (geo.coords.max_radius), # float(config['STATION']['maxradius']),
                    minradius=geo.coords.min_radius, # float(config['STATION']['minradius']),
                    maxradius=geo.coords.max_radius, # float(config['STATION']['maxradius']),
                    includerestricted=settings.station.include_restricted, # config['STATION']['includerestricted'],
                    level=settings.station.level.value
                )
            else:
                print(f"Unknown Geometry type: {geo.geo_type}")

            if inv:
                inv += curr_inv
            else:
                inv = curr_inv
    else: # No geographic constraint, search via inventory alone
        inv = station_client.get_stations(
            network=net,station=sta,
            location=loc,channel=cha, 
            starttime=starttime,endtime=endtime,
            level=settings.station.level.value
        )

    # Remove unwanted stations or networks
    if settings.station.exclude_stations: # config['STATION']['exclude_stations']:
        # exclude_list = config['STATION']['exclude_stations'].split(',') #format is NN.STA
        for ele in settings.station.exclude_stations:
            # n,s = ele.split('.')
            inv = inv.remove(network=ele.network.upper(),station=ele.station.upper())

    # Add anything else we were told to
    if settings.station.force_stations: # config['STATION']['force_stations']:
        # add_list = config['STATION']['force_stations'].split(',') #format is NN.STA
        for ele in settings.station.force_stations:
            # n,s = ele.split('.')
            try:
                inv += station_client.get_stations(
                    network=ele.network,
                    station=ele.station,
                    level=settings.station.level.value
                )
            except:
                # print("Could not find requested station %s at %s" % (ele,config['STATION']['client']))
                print("Could not find requested station %s at %s" % (ele.cmb_str,settings.station.client.value))
                continue

    return inv


def get_events(settings: SeismoLoaderSettings) -> List[Catalog]:
    starttime = UTCDateTime(settings.event.date_config.start_time)
    endtime = UTCDateTime(settings.event.date_config.end_time)
    waveform_client = Client(settings.waveform.client.value) # note we may have three different clients here: waveform, station, and event. be careful to keep track
    if settings.event and settings.event.client: # config['STATION']['client']:
        event_client = Client(settings.event.client.value) # Client(config['STATION']['client'])
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
    for geo in settings.event.geo_constraint:
        if geo.geo_type == GeoConstraintType.CIRCLE: # config['EVENT']['search_type'].lower() == 'radial':
            try:
                cat = event_client.get_events(
                    starttime=starttime,endtime=endtime,
                    minmagnitude= settings.event.min_magnitude, # float(config['EVENT']['minmagnitude']),
                    maxmagnitude= settings.event.max_magnitude, # float(config['EVENT']['maxmagnitude']),

                    latitude = geo.coords.lat, # float(config['EVENT']['latitude']),
                    longitude= geo.coords.lng, # float(config['EVENT']['longitude']),
                    # minradius= convert_radius_to_degrees(geo.coords.min_radius), # loat(config['EVENT']['minsearchradius']),
                    # maxradius= convert_radius_to_degrees(geo.coords.max_radius), # float(config['EVENT']['maxsearchradius']),
                    minradius= geo.coords.min_radius, # loat(config['EVENT']['minsearchradius']),
                    maxradius= geo.coords.max_radius, # float(config['EVENT']['maxsearchradius']),

                    #TODO add catalog,contributor
                    includeallorigins= settings.event.include_all_origins, # False,
                    includeallmagnitudes= settings.event.include_all_magnitudes, # False,
                    includearrivals= settings.event.include_arrivals, # False
                )
                print("Found %d events from %s" % (len(cat),settings.event.client.value))
                catalog.extend(cat)
            except:
                print("No events found!") #TODO elaborate
                # return catalog # sys.exit()
                
        elif geo.geo_type == GeoConstraintType.BOUNDING: # 'box' in config['EVENT']['search_type'].lower():
            try:
                cat = event_client.get_events(
                    starttime=starttime,endtime=endtime,
                    minmagnitude= settings.event.min_magnitude, # float(config['EVENT']['minmagnitude']),
                    maxmagnitude= settings.event.max_magnitude, # float(config['EVENT']['maxmagnitude']),
                    mindepth    = settings.event.min_depth,
                    maxdepth    = settings.event.max_depth,

                    minlatitude  = geo.coords.min_lat, # float(config['EVENT']['minlatitude']),
                    minlongitude = geo.coords.min_lng, # float(config['EVENT']['minlongitude']),
                    maxlatitude  = geo.coords.max_lat, # float(config['EVENT']['maxlatitude']),
                    maxlongitude = geo.coords.max_lng, # float(config['EVENT']['maxlongitude']),

                    #TODO add catalog,contributor
                    includeallorigins= settings.event.include_all_origins, # False,
                    includeallmagnitudes= settings.event.include_all_magnitudes, # False,
                    includearrivals= settings.event.include_arrivals, # False
                )
                print("Found %d events from %s" % (len(cat),settings.event.client.value))
                catalog.extend(cat)
            except:
                print("no events found!") #TODO elaborate
                # return # sys.exit()
        else:
            # FIXME: Once concluded on Geo Type, fix below terms: radial and box
            raise ValueError("Event search type: %s is invalid. Must be 'radial' or 'box'" % geo.geo_type.value)
        # sys.exit()   
    
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
    settings = setup_paths(settings)

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client.value) # note we may have three different clients here: waveform, station, and event. be careful to keep track

    # Collect requests
    requests = collect_requests(settings.station.selected_invs,starttime,endtime)

    # Remove any for data we already have (requires db be updated)
    pruned_requests= prune_requests(requests, settings.db_path)

    # Combine these into fewer (but larger) requests
    combined_requests = combine_requests(pruned_requests)

    waveform_clients= {'open':waveform_client}
    requested_networks = [ele[0] for ele in combined_requests]
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
            archive_request(request, waveform_client, settings.sds_path, settings.db_path)
        except:
            print("Continous request not successful: ",request)

    # Goint through all original requests
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
    settings = setup_paths(settings)

    waveform_client = Client(settings.waveform.client.value)
    
    ttmodel = TauPyModel(settings.event.model) #  config['EVENT']['model'])

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
        print("--> Downloading event (%d/%d) %s (%.4f lat %.4f lon %.1f km dep) ...\n" % (i+1,len(settings.event.selected_catalogs),eq.origins[0].time,eq.origins[0].latitude,eq.origins[0].longitude,eq.origins[0].depth/1000))

        # Collect requests
        requests = collect_requests_event_revised(
            eq, settings.station.selected_invs,
            before_p_sec=settings.event.before_p_sec if settings.event.before_p_sec else 10,
            after_p_sec=settings.event.after_p_sec if settings.event.after_p_sec else 120,
            model=ttmodel,
            settings=settings
        )

        # Remove any for data we already have (requires db be updated)
        pruned_requests= prune_requests(requests, settings.db_path)

        # Combine these into fewer (but larger) requests
        # this probably makes little for sense EVENTS, but its inexpensive and good for testing purposes
        combined_requests = combine_requests(pruned_requests)

        # Add additional clients if user is requesting any restricted data
        waveform_clients= {'open':waveform_client}
        requested_networks = [ele[0] for ele in combined_requests]

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
            time.sleep(0.05) #to help ctrl-C out if needed
            print(request)
            try: 
                archive_request(request,waveform_client,settings.sds_path,settings.db_path)
            except Exception as e:
                print("Event request not successful: ",request, str(e))
        
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



def run_main(settings: SeismoLoaderSettings = None, from_file=None):
    if not settings and from_file:
        settings = SeismoLoaderSettings()
        settings = settings.from_cfg_file(cfg_path = from_file)

    settings = setup_paths(settings)

    download_type = settings.download_type.value # config['PROCESSING']['download_type'].lower()
    if not is_in_enum(download_type, DownloadType):
        download_type = DownloadType.CONTINUOUS # 'continuous' # default


    if download_type == DownloadType.CONTINUOUS:
        settings.station.selected_invs = get_stations(settings)
        run_continuous(settings)

    if download_type == DownloadType.EVENT:
        settings.event.selected_catalogs = get_events(settings)
        settings.station.selected_invs     = get_stations(settings)
        run_event(settings)
    # Now we can optionally clean up our database (stich continous segments, etc)
    print("\n ~~ Cleaning up database ~~")
    join_continuous_segments(settings.db_path, settings.proccess.gap_tolerance) # gap_tolerance=float(config['PROCESSING']['gap_tolerance']))

    # And print the contents (first 100 elements), for now (DEBUG / TESTING feature)
    display_database_contents(settings.db_path,100)


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

    

