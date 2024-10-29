#!/usr/bin/env python3

# CLI SDS data downloader/archiver/database management, use: $ ./seedvault.py example_event.cfg

#requirements: obspy, tqdm, tabulate, sqlite3, contexlib

# ver 0.40 16/10/24
# - complete remodel of database manager
# -   database now includes a table for event-station EQ & arrival info
# - refactoring all database calls/operations
# - small bugs etc

# ver 0.33 
# - some typos, bugs fixed
# - force stations and NSLC to be uppercase

# ver 0.32 22/09/2024
# - finish adding auth capability, change format in config files
# - add "catalog" option to [EVENT] settings to use a pre-downloaded "QuakeML" xml catalog instead searching for and downloadin one
# - remove .lower() to process config items as this is done by default
# - allow some config settings to be case sensitive (e.g. AUTH)
# - add "dist_deg" kwarg to get_p_s_times instead of calculating it twice

# ver 0.31 06/09/2024
# - select only highest samplerate channels for event downloads

# ver 0.3 04/09/2024
# - add event capability, add example continuous/event cfg files, fix a LOT of bugs, other significant renames/structural changes

# ver 0.2 08/2024
# - first shared edition


### TODO:
# catagorize HTTP error codes (e.g. 204 = no data)
# incoroporate function to output only "preferred" channels or location codes
# remove data where original SDS files no longer exist in "populate_database_sds"
# check multiprocessing (how it is currently written) is functional in OSX/Windows

import os
import sys
import time
import sqlite3
import datetime
import multiprocessing
import configparser
import contextlib
import fnmatch
from tqdm import tqdm
from collections import defaultdict
# no longer using / from tabulate import tabulate # non-standard. this is just to display the db contents


import obspy
from obspy.clients.fdsn import Client
from obspy.geodetics.base import locations2degrees,gps2dist_azimuth
from obspy import UTCDateTime
from obspy.taup import TauPyModel

class CustomConfigParser(configparser.ConfigParser):
    def __init__(self, *args, **kwargs):
        self.case_sensitive_sections = set()
        super().__init__(*args, **kwargs)

    def optionxform(self, optionstr):
        return optionstr  # Always return the original string

def read_config(config_file):
    config = CustomConfigParser(allow_no_value=True)
    config.read(config_file)
    
    # Process the config, preserving case where asked and converting others to lowercase
    processed_config = CustomConfigParser(allow_no_value=True)
    
    for section in config.sections():
        processed_config.add_section(section)
        for key, value in config.items(section):
            if section in ['AUTH','DATABASE','SDS','WAVEFORM']:
                # Preserve case for both key and value in AUTH section
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


class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.setup_database()

    @contextlib.contextmanager
    def connection(self, max_retries=3, initial_delay=1):
        """Context manager for safe database connections with retry mechanism."""
        retry_count = 0
        delay = initial_delay
        while retry_count < max_retries:
            try:
                conn = sqlite3.connect(self.db_path, timeout=20)
                yield conn
                conn.commit()
                return
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"Failed to connect to database after {max_retries} retries.")
                        raise
                    print(f"Database is locked. Retrying in {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                    delay += random.uniform(0, 1)  # Add jitter
                else:
                    raise
            finally:
                if 'conn' in locals():
                    conn.close()

    def setup_database(self):
        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Create archive_data table
            # starttime and endtime are isoformat, importtime is timestamp
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archive_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    network TEXT,
                    station TEXT,
                    location TEXT,
                    channel TEXT,
                    starttime TEXT,
                    endtime TEXT,
                    importtime REAL
                )
            ''')
            
            # Create index for archive_data
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_archive_data 
                ON archive_data (network, station, location, channel, starttime, endtime, importtime)
            ''')
            
            # Create arrival_data table
                # event_id / unique eventID which usually points to a web address
                #e_mag / earthquake magnitude
                #e_lat / earthquake origin latitude
                #e_lon / earthquake origin longitude
                #e_depth / earthquake depth (km)
                #e_time / earthquake origin time (utc)
                #s_netcode / station network code
                #s_stacode / station station code
                #s_lat / station latitude
                #s_lon / station longitude
                #s_elev / station elevation (km)
                #s_start / station start date (timestamp) * some scenarios where there are multiple stations at different times
                #s_end / station end date (timestamp) * NULL if station is still running
                #dist_deg / distance between event and station in degrees
                #dist_km / distance between event and station in km
                #azimuth / azimuth from EVENT to STATION
                #p_arrival / estimated p arrival at station (timestamp)
                #s_arrival / estimated S arrival at station (timestamp)
                #model / 1D earth model used in TauP
                #importtime / timestamp
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS arrival_data (
                    event_id TEXT,
                    e_mag REAL,
                    e_lat REAL,
                    e_lon REAL,
                    e_depth REAL,
                    e_time REAL,
                    s_netcode TEXT,
                    s_stacode TEXT,
                    s_lat REAL,
                    s_lon REAL,
                    s_elev REAL,
                    s_start REAL,
                    s_end REAL,
                    dist_deg REAL,
                    dist_km REAL,
                    azimuth REAL,
                    p_arrival REAL,
                    s_arrival REAL,
                    model TEXT,
                    importtime,
                    PRIMARY KEY (event_id, s_netcode, s_stacode, s_start)
                )
            ''')

    def display_contents(self, table_name, start_time=0, end_time=4102444799, limit=100):
        """
        Display the contents of a specified table within a given time range.
        
        :param table_name: Name of the table to query (e.g., 'archive_data' or 'arrival_data')
        :param starttime: Start time for the query (can be timestamp, datetime, or UTCDateTime)
        :param endtime: End time for the query (can be timestamp, datetime, or UTCDateTime)
        :param limit: Maximum number of rows to return
        """
        try:
            start_timestamp = to_timestamp(start_time)
            end_timestamp = to_timestamp(end_time)
        except ValueError as e:
            print(f"Error converting time: {str(e)}")
            return

        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Get column names
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Construct and execute query
            query = f"""
                SELECT * FROM {table_name}
                WHERE importtime BETWEEN ? AND ?
                ORDER BY importtime
                LIMIT ?
            """
            cursor.execute(query, (start_timestamp, end_timestamp, limit))
            
            # Fetch results
            results = cursor.fetchall()
            
            # Print results
            print(f"\nContents of {table_name} (limited to {limit} rows):")
            print("=" * 80)
            print(" | ".join(columns))
            print("=" * 80)
            for row in results:
                print(" | ".join(str(item) for item in row))
            
            print(f"\nTotal rows: {len(results)}")

    # tools to clean / maintain tables if they get very large or many elements deleted (not currently implemented)
    def reindex_archive_data(self):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("REINDEX idx_archive_data")

    def vacuum_database(self):
        with self.connection() as conn:
            conn.execute("VACUUM")

    def analyze_table(self, table_name):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"ANALYZE {table_name}")

    def delete_elements(self, table_name, start_time=0, end_time=4102444799):
        """ Delete elements from table_name between start and end_time """

        if table_name.lower() not in ['archive_data','arrival_data']:
            print("table_name must be archive_data or arrival_data")
            return 0

        try:
            start_timestamp = to_timestamp(start_time)
            end_timestamp = to_timestamp(end_time)
        except ValueError as e:
            raise ValueError(f"Invalid time format: {str(e)}")

        with self.connection() as conn:
            cursor = conn.cursor()
            
            query = f'''
                DELETE FROM {table_name}
                WHERE importtime >= ? AND importtime <= ?
            '''
            
            cursor.execute(query, (start_timestamp, end_timestamp))
            
            deleted_count = cursor.rowcount
            
            return deleted_count

    def run_query(self,query):
        """Run any query!"""
        with self.connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query)
            except sqlite3.Error as e:
                print(f"SQLite error: {e}")
                # Print the SQL statement and the data being inserted
        return

    def bulk_insert_archive_data(self, archive_list):
        if not archive_list:
            return 0

        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Add import time
            now = int(datetime.datetime.now().timestamp())
            archive_list = [tuple(list(ele) + [now]) for ele in archive_list if ele is not None]

            inserted = 0
            cursor.executemany('''
                INSERT OR REPLACE INTO archive_data
                (network, station, location, channel, starttime, endtime, importtime)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', archive_list)
            
            return cursor.rowcount

    def bulk_insert_arrival_data(self, arrival_list):
        if not arrival_list:
            return 0

        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Define the columns based on your table structure
            columns = ['event_id', 'e_mag', 'e_lat', 'e_lon', 'e_depth', 'e_time',
                   's_netcode', 's_stacode', 's_lat', 's_lon', 's_elev', 's_start', 's_end',
                   'dist_deg', 'dist_km', 'azimuth', 'p_arrival', 's_arrival', 'model',
                   'importtime']
            
            placeholders = ', '.join(['?' for _ in columns])
            
            query = f'''
                INSERT OR REPLACE INTO arrival_data
                ({', '.join(columns)})
                VALUES ({placeholders})
            '''
            
            # Add import time
            now = int(datetime.datetime.now().timestamp())
            arrival_list = [tuple(list(ele) + [now]) for ele in arrival_list]

            # Perform the bulk insert
            cursor.executemany(query, arrival_list)
            
            return cursor.rowcount

    def get_arrival_data(self, event_id, netcode, stacode):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arrival_data 
                WHERE event_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (event_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                columns = [description[0] for description in cursor.description]
                return dict(zip(columns, result))
        return None

    def get_stations_for_event(self, event_id):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arrival_data 
                WHERE event_id = ?
            ''', (event_id,))
            results = cursor.fetchall()
            if results:
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, result)) for result in results]
        return []

    def get_events_for_station(self, netcode, stacode):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arrival_data 
                WHERE s_netcode = ? AND s_stacode = ?
            ''', (netcode, stacode))
            results = cursor.fetchall()
            if results:
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, result)) for result in results]
        return []

    def fetch_arrivals(self, event_id, netcode, stacode):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p_arrival, s_arrival 
                FROM arrival_data 
                WHERE event_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (event_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                return (result[0], result[1])
        return None


def miniseed_to_db_element(file_path):
    "Create a database element from a miniseed file"
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

def stream_to_db_element(st):
    """Create a database element from a stream 
    (assuming all traces have same NSLC!)
    just a bit faster than re-opening the file again"""

    if len(st) == 0:
        print(f"Warning: No traces found in {file_path}")
        return None
        
    start_time = min(tr.stats.starttime for tr in st)
    end_time = max(tr.stats.endtime for tr in st)
        
    return (st[0].stats.network, st[0].stats.station, \
        st[0].stats.location, st[0].stats.channel, \
         start_time.isoformat(), end_time.isoformat())


## TODO remove data where original SDS files no longer exist?
## this can take a long time for someone with a serious archive already (5TB / 768235 files = ~8-12 hours at 4 cores)

def populate_database_from_sds(sds_path, db_path,
    search_patterns=["??.*.*.???.?.????.???"],
    newer_than=None,num_processes=None):

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

def join_continuous_segments__OLD(db_path, gap_tolerance=60):
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

"""
def reset_id_counter(db_manager, table_name):

    #Reset the ID counter for a specified table in the SQLite database.
    #
    #:param db_manager: DatabaseManager instance
    #:param table_name: Name of the table whose ID counter should be reset

    with db_manager.safe_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get the maximum ID currently in the table
        cursor.execute(f"SELECT MAX(id) FROM {table_name}")
        max_id = cursor.fetchone()[0] or 0
        
        # Reset the SQLite sequence
        cursor.execute(f"UPDATE sqlite_sequence SET seq = {max_id} WHERE name = ?", (table_name,))
        
        # If the table doesn't exist in sqlite_sequence, insert it
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table_name, max_id))
    
    print(f"Reset ID counter for table '{table_name}' to {max_id}")
"""


"""
def display_database_contents(db_manager, limit=100):
    "
    Display the contents of the SQLite database using a safe connection.
    
    :param db_manager: DatabaseManager instance
    :param limit: Number of rows to display (default is 100, use None for all rows)
    "
    with db_manager.connection() as conn:
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
"""


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
def get_p_s_times(eq,dist_deg,sta_lat,sta_lon,ttmodel):
    eq_lat = eq.origins[0].latitude
    eq_lon = eq.origins[0].longitude
    eq_depth = eq.origins[0].depth / 1000 # note that depths are in Meters for QuakeML

    try:
        phasearrivals = ttmodel.get_travel_times(source_depth_in_km=eq_depth,distance_in_degree=dist_deg,phase_list=['ttbasic']) #ttp or "ttbasic" or ttall may want to try S picking eventually
    except:
        try:
            phasearrivals = ttmodel.get_travel_times(source_depth_in_km=0,distance_in_degree=dist_deg,phase_list=['ttbasic']) #possibly depth issue if negetive.. OK we only need to "close" anyway
        except:
            return None,None

    try:
        p_duration = phasearrivals[0].time #seconds it takes for p-wave to reach station
    except: # TODO print enough info to explain why.. many possible reasons!
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
cha_rank = ['FH','CH','HH','BH','SH','GH','DH','EH','HN','EN','LH']
# loc_rank = ['','10','00','20'] # sort of dangerous as this is rarely done consistently
def TOFIX__output_best_channels(nn,sta,t):
        if type(sta) != obspy.core.inventory.station.Station:
                print("get_best_nslc: not station input!")
                return sta.channels
        if len(sta) < 2 : return sta.channels
        CHs = set([ele.code[0:2] for ele in sta.channels])
        if len(CHs) == 1:
                return [sta.channels[0]]

        # Re-assess what channels are available. These should be sorted by samplerate with the highest first. 
        #   Should be enough for most cases, but...
        for cha in sta.channels:
            if cha.end_date is None: cha.end_date = UTCDateTime(2099,1,1) # Easiest to replace all "None" with "far off into future"
        CHs = set([tr.stats.channel[0:2] for tr in st])
        for ch in cha_rank:
            selection = [ele for ele in sta.channels if ele.code[0:2] == ch and ele.start_date <= t <= ele.end_date]
            if selection:
                return selection
        print("no valid channels found in output_best_channels")
        return []

def select_highest_samplerate(inv,time=None):
    """
    Where overlapping channels exist (e.g. 100 hz and 10 hz), filter out anything other than highest available samplerate
    Presumably, users will always want the highest samplerate for events
    Best to set time, otherwise will remove regardless of time
    """
    if time:
        inv = inv.select(time=time)
    for net in inv:
        for sta in net:
            srs = list(set([ele.sample_rate for ele in sta.channels]))
            if len(srs) < 2:
                continue
            sta.channels = [ele for ele in sta.channels if ele.sample_rate == max(srs)]
    return inv

def collect_requests_event(eq,inv,min_dist_deg=30,max_dist_deg=90,before_p_sec=10,after_p_sec=120,model=None): #todo add params for before_p, after_p, etc
    """ collect all requests for data in inventory for given event eq """

    # n.b. "eq" is an earthquake object, e.g. one element of the array collected in a "catalog" object

    origin = eq.origins[0] # default to the primary I suppose (possible TODO but don't see why anyone would want anything else)
    ot = origin.time

    sub_inv = select_highest_samplerate(inv,time=ot) #select only stations online during earthquake start, as well as only highest SR channels

    requests_per_eq = []
    arrivals_per_eq = []
    for net in sub_inv:
        for sta in net:

            # Check if we've already calculated this event-station pair
            fetched_arrivals = db_manager.fetch_arrivals(str(eq.preferred_origin_id), \
                               net.code,sta.code) #TODO also check models are consistent

            if fetched_arrivals:
                p_time,s_time = fetched_arrivals # timestamps
                t_start = p_time - abs(before_p_sec)
                t_end = s_time + abs(after_p_sec)           
            else:
                dist_deg = locations2degrees(origin.latitude,origin.longitude,\
                                             sta.latitude,sta.longitude)
                dist_m,azi,backazi = gps2dist_azimuth(origin.latitude,origin.longitude,\
                                             sta.latitude,sta.longitude)
                if dist_deg < min_dist_deg or dist_deg > max_dist_deg:
                    continue
                p_time, s_time = get_p_s_times(eq,dist_deg,sta.latitude,sta.longitude,model) #not timestamp!
                if not p_time: continue # TOTO need error msg also

                t_start = p_time - abs(before_p_sec) #not timestamps!
                t_end = p_time + abs(after_p_sec)

                t_start = t_start.timestamp
                t_end = t_end.timestamp

                # add to our arrival database
                arrivals_per_eq.append((str(eq.preferred_origin_id),
                                    eq.magnitudes[0].mag,
                                    origin.latitude, origin.longitude,origin.depth/1000,
                                    ot.timestamp,
                                    net.code,sta.code,sta.latitude,sta.longitude,sta.elevation/1000,
                                    sta.start_date.timestamp,sta.end_date.timestamp,
                                    dist_deg,dist_m/1000,azi,p_time.timestamp,
                                    s_time.timestamp,config['EVENT']['model']))

            # add to our requests
            for cha in sta: # TODO will have to had filtered channels prior to this, else will grab them all
                requests_per_eq.append((
                    net.code,
                    sta.code,
                    cha.location_code,
                    cha.code,
                    datetime.datetime.fromtimestamp(t_start).isoformat() + "Z",
                    datetime.datetime.fromtimestamp(t_end).isoformat() + "Z" ))

    return requests_per_eq, arrivals_per_eq

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


def prune_requests(requests, db_manager, min_request_window=2):
    """
    Remove any overlapping requests where already-archived data may exist 
    If any requests are less than min_request_window seconds, ignore
    
    :param requests: List of request tuples (network, station, location, channel, start_time, end_time)
    :param db_manager: DatabaseManager instance
    :param min_request_window: Minimum request window in seconds
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
                        pruned_requests.append((network, station, location, channel, 
                                                current_time.isoformat(), db_start.isoformat()))
                    
                    current_time = max(current_time, db_end)
                
                if current_time < end_time - min_request_window:
                    # There's a gap after the last existing data
                    pruned_requests.append((network, station, location, channel, 
                                            current_time.isoformat(), end_time.isoformat()))
    
    return pruned_requests

def archive_request(request, waveform_clients, sds_path, db_manager):
    """ Send a request to an FDSN center, parse it, save to archive, and update our database """
    try:
        if request[0] in waveform_clients.keys():  # Per-network authentication
            wc = waveform_clients[request[0]]
        elif request[0]+'.'+request[1] in waveform_clients.keys():  # Per-station e.g. if there is only a password for one station NN.SSSSS
            wc = waveform_clients[request[0]+'.'+request[1]]
        else:
            wc = waveform_clients['open']
        
        st = wc.get_waveforms(network=request[0], station=request[1],
                              location=request[2], channel=request[3],
                              starttime=UTCDateTime(request[4]), endtime=UTCDateTime(request[5]))
    except Exception as e:
        print(f"Error fetching data: {request} {str(e)}")
        # >> TODO add failure & denied to database also. can grep from HTTP status code (204 = no data, etc)
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
        
        current_time = UTCDateTime(starttime.date)
        while current_time < endtime:
            year = current_time.year
            doy = current_time.julday
            
            next_day = current_time + 86400 
            day_end = min(next_day - tr.stats.delta, endtime)
            
            day_tr = tr.slice(current_time, day_end)
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
            existing_st = obspy.read(full_path)
            existing_st += day_stream
            existing_st.merge(method=-1, fill_value=None)
            existing_st._cleanup()
            print(f"  merging {full_path}")
        else:
            existing_st = day_stream
            print(f"  writing {full_path}")
        
        existing_st.write(full_path, format="MSEED", reclen=4096, encoding='STEIM2')

        to_insert_db.append(stream_to_db_element(existing_st))

    # Update database
    try:
        num_inserted = db_manager.bulk_insert_archive_data(to_insert_db)
    except Exception as e:
        print("Error with bulk_insert_archive_data: ", e)



################ end function declarations, start program


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 seismoloader.py input.cfg")
        sys.exit(1)
    
    config_file = sys.argv[1]
    try:
        config = read_config(config_file)
    except:
        print("Cannot read configuration file", config_file)
        sys.exit(1)

    sds_path = config['SDS']['sds_path']
    if not sds_path:
        print("SDS Path not set!!!")
        sys.exit(1)

    db_path = config['DATABASE']['db_path']
    if not db_path:
        db_path = os.path.join(sds_path,"database.sql")

    # Setup SDS directory
    if not os.path.exists(sds_path):
        os.makedirs(sds_path)

    # Setup database manager (also sets up database itself)
    db_manager = DatabaseManager(db_path)

    download_type = config['PROCESSING']['download_type']
    if download_type not in ['continuous','event']:
        download_type = 'continuous' # default

    if download_type == 'continuous':
        starttime = UTCDateTime(config['STATION']['starttime'])
        endtime = UTCDateTime(config['STATION']['endtime'])

    else: #assume "event"
        starttime = UTCDateTime(config['EVENT']['starttime'])
        endtime = UTCDateTime(config['EVENT']['endtime'])

    waveform_client = Client(config['WAVEFORM']['client']) # note we may have three different clients here: waveform, station, and event. be careful to keep track
    if config['STATION']['client']:
        station_client = Client(config['STATION']['client'])
    else:
        station_client = waveform_client

    if config['PROCESSING']['download_type'] == 'event' and config['EVENT']['client']:
        event_client = Client(config['EVENT']['client'])
    else:
        event_client = waveform_client


    days_per_request = int(config['WAVEFORM']['days_per_request'])
    if not days_per_request:
        days_per_request = 2 # a resonable default?

    # if user is specifying / filtering, use these in N.S.L.C order
    net = config['STATION']['network'].upper()
    if not net:
        net = '*'
    sta = config['STATION']['station'].upper()
    if not sta:
        sta = '*'
    loc = config['STATION']['location'].upper()
    if not loc:
        loc = '*'
    cha = config['STATION']['channel'].upper()
    if not cha:
        cha = '*'

    # User has specified this specific pre-existing (filepath) inventory to use instead of searching for one
    if config['STATION']['local_inventory']:
        try:
            inv = obspy.read_inventory(config['STATION']['local_inventory'])
        except:
            print("Could not load requested inventory %s" % config['STATION']['local_inventory'])

    elif not config['STATION']['local_inventory'] and \
    config['STATION']['geo_constraint'] in ['box','bounding']:
        ## TODO Test if all variables exist / error if not
        inv = station_client.get_stations(network=net,station=sta,
                                 location=loc,channel=cha,
                                 starttime=starttime,endtime=endtime,
            minlatitude=float(config['STATION']['minlatitude']),
            maxlatitude=float(config['STATION']['maxlatitude']),
            minlongitude=float(config['STATION']['minlongitude']),
            maxlongitude=float(config['STATION']['maxlongitude']),
            includerestricted=config['STATION']['includerestricted'],
            level='channel'
            )
    elif not config['STATION']['local_inventory'] and \
    config['STATION']['geo_constraint'] in ['circle','radial']:
        ## TODO Test if all variables exist / error if not
        inv = station_client.get_stations(network=net,station=sta,
                                 location=loc,channel=cha,
                                 starttime=starttime,endtime=endtime,
            latitude=float(config['STATION']['latitude']),
            longitude=float(config['STATION']['longitude']),
            minradius=float(config['STATION']['minradius']),
            maxradius=float(config['STATION']['maxradius']),
            includerestricted=config['STATION']['includerestricted'],
            level='channel'
            )

    else: # No geographic constraint, search via inventory alone
        #print(net,sta,loc,cha,starttime,endtime)
        inv = station_client.get_stations(network=net,station=sta,
                                  location=loc,channel=cha,
                                  starttime=starttime,endtime=endtime,level='channel')

    # Remove unwanted stations or networks
    if config['STATION']['exclude_stations']:
        exclude_list = config['STATION']['exclude_stations'].upper().split(',') #format is NN.STA
        for ele in exclude_list:
            n,s = ele.split('.')
            inv = inv.remove(network=n.upper(),station=s.upper())

    # Add anything else we were told to
    if config['STATION']['force_stations']:
        add_list = config['STATION']['force_stations'].upper().split(',') #format is NN.STA
        for ele in add_list:
            n,s = ele.split('.')
            try:
                inv += station_client.get_stations(network=n,station=s,level='channel')
            except:
                print("Could not find requested station %s at %s" % (ele,config['STATION']['client']))
                continue

    if config['PROCESSING']['download_type'] == 'event':
        ttmodel = TauPyModel(config['EVENT']['model'])
        event_client = Client(config['EVENT']['client'])

        minradius = float(config['EVENT']['minradius'])
        maxradius = float(config['EVENT']['maxradius'])

        # Read catalog from file, if requested
        if config['EVENT']['local_catalog']:
            try:
                catalog = obspy.read_events(config['EVENT']['local_catalog'])
            except:
                print("Could not read requested catalog %s" % config['EVENT']['local_catalog'])
                sys.exit()
        else:
            catalog = None

        if config['EVENT']['geo_constraint'] in ['circle','radial']:
            if not catalog:
                try:
                    catalog = event_client.get_events(
                        starttime=starttime,endtime=endtime,
                        minmagnitude=float(config['EVENT']['minmagnitude']),
                        maxmagnitude=float(config['EVENT']['maxmagnitude']),

                        latitude=float(config['EVENT']['latitude']),
                        longitude=float(config['EVENT']['longitude']),
                        minradius=float(config['EVENT']['minsearchradius']),
                        maxradius=float(config['EVENT']['maxsearchradius']),

                        #TODO add catalog,contributor
                        includeallorigins=False,
                        includeallmagnitudes=False,
                        includearrivals=False)
                    print("Found %d events from %s" % (len(catalog),config['STATION']['client']))
                except:
                    print("No events found!") #TODO elaborate
                    sys.exit()
            #TODO: filter existing/saved catalog based on search parameters as well
        elif config['EVENT']['search_type'] in ['box','bounding']:
            if not catalog:
                try:
                    catalog = event_client.get_events(
                        starttime=starttime,endtime=endtime,
                        minmagnitude=float(config['EVENT']['minmagnitude']),
                        maxmagnitude=float(config['EVENT']['maxmagnitude']),

                        minlatitude=float(config['EVENT']['minlatitude']),
                        minlongitude=float(config['EVENT']['minlongitude']),
                        maxlatitude=float(config['EVENT']['maxlatitude']),
                        maxlongitude=float(config['EVENT']['maxlongitude']),

                        #TODO add catalog,contributor
                        includeallorigins=False,
                        includeallmagnitudes=False,
                        includearrivals=False)
                    print("Found %d events from %s" % (len(catalog),config['STATION']['client']))
                except:
                    print("no events found!") #TODO elaborate
                    sys.exit()
        else:
            print("Event search type: %s is invalid. Must be 'circle/radial','box/bounding'" % config['EVENT']['search_type'])
            sys.exit()         

        # Loop through events
        for i,eq in enumerate(catalog):
            print("--> Downloading event (%d/%d) %s (%.4f lat %.4f lon %.1f km depth) ...\n" % (i+1,len(catalog),
                eq.origins[0].time,eq.origins[0].latitude,eq.origins[0].longitude,eq.origins[0].depth/1000))

            # Define event windows relative to estimated P arrival
            if config['EVENT']['before_p_sec']:
                p_before = float(config['EVENT']['before_p_sec'])
            else:
                p_before = 10 # a resonable default?
            if config['EVENT']['after_p_sec']:
                p_after = float(config['EVENT']['after_p_sec'])
            else:
                p_after = 120 # a resonable default?               

            # Collect requests
            requests,new_arrivals = collect_requests_event(eq,inv,min_dist_deg=minradius,max_dist_deg=maxradius,
                                              before_p_sec=p_before,after_p_sec=p_after,model=ttmodel) #TODO make before p and after p configurable

            # Import any new arrival info into our database
            if new_arrivals:
                db_manager.bulk_insert_arrival_data(new_arrivals)
                print(" ~ %d new arrivals added to database" % len(new_arrivals))

            # Remove any for data we already have (requires db to be updated)
            pruned_requests= prune_requests(requests, db_manager)

            # Skip out if there aren't any requests left!
            if len(pruned_requests) == 0:
                print("--> Event already downloaded (%d/%d) %s (%.4f lat %.4f lon %.1f km dep) ...\n" % (i+1,len(catalog),
                eq.origins[0].time,eq.origins[0].latitude,eq.origins[0].longitude,eq.origins[0].depth/1000))
                continue

            # Combine these into fewer (but larger) requests
            # (n.b. this probably makes little for sense EVENTS, but no harm in it)
            combined_requests = combine_requests(pruned_requests)

            # Add additional clients if user is requesting any restricted data
            waveform_clients= {'open':waveform_client}
            requested_networks = [ele[0] for ele in combined_requests]
            credentials = list(config['AUTH'].items())
            for ele in credentials:
                if ele[0].split('.')[0] not in requested_networks:
                    continue
                uname,pw = ele[1].split(':')
                try:
                    new_client = Client(config['WAVEFORM']['client'],user=uname,password=pw)
                except:
                    print("Issue creating client: %s %s via %s:%s" % (config['WAVEFORM']['client'],ele[0],uname,pw))
                    continue
                waveform_clients.update({ele[0]:new_client})

            # Archive to disk and updated database
            for request in combined_requests:
                time.sleep(0.05) # to help ctrl-C break out if needed
                print(request)
                try: 
                    archive_request(request,waveform_clients,sds_path,db_manager)
                except:
                    print("Event request not successful: ",request)

    else: # Continuous Data downloading
        # Collect requests
        requests = collect_requests(inv,starttime,endtime,days_per_request=days_per_request)

        # Remove any for data we already have (requires db be updated)
        pruned_requests= prune_requests(requests, db_manager)

        if len(pruned_requests) > 0:

            # Combine these into fewer (but larger) requests
            combined_requests = combine_requests(pruned_requests)

            # Add additional clients if user is requesting any restricted data
            waveform_clients= {'open':waveform_client}
            requested_networks = [ele[0] for ele in combined_requests]
            credentials = list(config['AUTH'].items())
            for ele in credentials:
                if ele[0].split('.')[0] not in requested_networks:
                    continue
                uname,pw = ele[1].split(':')
                try:
                    new_client = Client(config['WAVEFORM']['client'],user=uname,password=pw)
                except:
                    print("Issue creating client: %s %s via %s:%s" % (config['WAVEFORM']['client'],ele[0],uname,pw))
                    continue
                waveform_clients.update({ele[0]:new_client})

            # Archive to disk and updated database
            for request in combined_requests:
                print(request)
                time.sleep(0.05) #to help ctrl-C out if needed
                try: 
                    archive_request(request,waveform_clients,sds_path,db_manager)
                except:
                    print("Continous request not successful: ",request)


    # Now we can optionally clean up our database (stich continous segments, etc)
    print("\n ~~ Cleaning up database ~~")
    join_continuous_segments(db_manager, gap_tolerance=float(config['PROCESSING']['gap_tolerance']))

    # And print the contents (first 100 elements), for now (DEBUG / TESTING feature)
    #display_database_contents(db_manager,100)
    db_manager.display_contents('arrival_data',start_time=0, end_time=4102444799, limit=100)
    db_manager.display_contents('archive_data',start_time=0, end_time=4102444799, limit=100)    


