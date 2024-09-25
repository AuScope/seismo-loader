#!/usr/bin/env python3

# CLI SDS data downloader/archiver/database management, use: $ ./seismoloader.py example_event.cfg

#requirements: obspy, tqdm, tabulate, sqlite3, contexlib

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
# add a "files newer than" search filter in "populate_database_sds"
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
from tqdm import tqdm
from tabulate import tabulate # non-standard. this is just to display the db contents

import obspy
from obspy.clients.fdsn import Client
from obspy.geodetics.base import locations2degrees
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

def setup_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS archive_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            network TEXT,
            station TEXT,
            location TEXT,
            channel TEXT,
            starttime TEXT,
            endtime TEXT
            )
        ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_archive_data 
        ON archive_data (network, station, location, channel, starttime, endtime)
        ''')
    conn.commit()
    return

@contextlib.contextmanager
def safe_db_connection(db_path, max_retries=3, initial_delay=1):
    """Context manager for safe database connections with retry mechanism."""
    retry_count = 0
    delay = initial_delay
    while retry_count < max_retries:
        try:
            conn = sqlite3.connect(db_path, timeout=20)
            yield conn
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
cha_rank = ['CH','HH','BH','EH','HN','EN','SH','LH']
loc_rank = ['','10','00','20'] # sort of dangerous as this is rarely done consistently
def TOFIX__output_best_channels(nn,sta,t):
        if type(sta) != obspy.core.inventory.station.Station:
                print("get_best_nslc: not station input!")
                return sta.channels
        if len(sta) <=1 : return sta.channels
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
            if selection: return selection
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
    for net in sub_inv:
        for sta in net:
            dist_deg = locations2degrees(sta.latitude,sta.longitude,origin.latitude,origin.longitude)
            if dist_deg < min_dist_deg or dist_deg > max_dist_deg:
                continue
            p_time, s_time = get_p_s_times(eq,dist_deg,sta.latitude,sta.longitude,model)
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

def archive_request(request,waveform_clients,sds_path,db_path):
    """ Send a request to an FDSN center, parse it, save to archive, and update our database """
    try:
        if request[0] in waveform_clients.keys(): # Per-network authentication
            wc = waveform_clients[request[0]]
        elif request[0]+'.'+request[1] in waveform_clients.keys(): # Per-station e.g. if there is only a password for one station NN.SSSSS
            wc = waveform_clients[request[0]]
        else:
            wc = waveform_clients['open']

        st = wc.get_waveforms(network=request[0],station=request[1],
                    location=request[2],channel=request[3],
                    starttime=UTCDateTime(request[4]),endtime=UTCDateTime(request[5]))
    except Exception as e:
        print(f"Error fetching data: {request} {str(e)}")
        # >> TODO add failure & denied to database also. can grep from HTTP status code (204 = no data, etc)
        return

    # Now loop through traces
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
                existing_st._cleanup() # gets rid of any overlaps, sub-sample jitter / TODO decide on a default or let user change?
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

    # Setup database
    if not os.path.exists(db_path):
        setup_database(db_path)

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


    days_per_request = config['WAVEFORM']['days_per_request']
    if not days_per_request:
        days_per_request = 3 # a resonable default? It probably will have to depend on the total number of samples of the request (TODO)

    # if user is specifying / filtering, use these in N.S.L.C order
    net = config['STATION']['network']
    if not net:
        net = '*'
    sta = config['STATION']['station']
    if not sta:
        sta = '*'
    loc = config['STATION']['location']
    if not loc:
        loc = '*'
    cha = config['STATION']['channel']
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
        inv = station_client.get_stations(network=net,station=sta,
                                  location=loc,channel=cha,
                                  starttime=starttime,endtime=endtime,level='channel')

    # Remove unwanted stations or networks
    if config['STATION']['exclude_stations']:
        exclude_list = config['STATION']['exclude_stations'].split(',') #format is NN.STA
        for ele in exclude_list:
            n,s = ele.split('.')
            inv = inv.remove(network=n.upper(),station=s.upper())

    # Add anything else we were told to
    if config['STATION']['force_stations']:
        add_list = config['STATION']['force_stations'].split(',') #format is NN.STA
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

        if config['EVENT']['geo_constraint'] in ['circle','bounding']:
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
        elif config['EVENT']['geo_constraint'] in ['bounding','circle']:
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
            print("Event search type: %s is invalid. Must be 'circle/radial','box/bounding'" % config['EVENT']['geo_constraint'])
            sys.exit()         

        #now loop through events
        # NOTE: Why "inv" collections from STATION block is included in EVENTS?
        #       Isn't it the STATIONS have their own searching settings?
        #       If the search settings such as map search and time search are the
        #       same, why separate parameters are defined for events?
        for i,eq in enumerate(catalog):
            print("--> Downloading event (%d/%d) %s (%.4f lat %.4f lon %.1f km dep) ...\n" % (i+1,len(catalog),
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
            requests = collect_requests_event(eq,inv,min_dist_deg=minradius,max_dist_deg=maxradius,
                                              before_p_sec=p_before,after_p_sec=p_after,model=ttmodel) #TODO make before p and after p configurable

            # Remove any for data we already have (requires db be updated)
            pruned_requests= prune_requests(requests, db_path)

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
                    archive_request(request,waveform_clients,sds_path,db_path)
                except:
                    print("Event request not successful: ",request)

    else: # Continuous Data downloading
        # Collect requests
        requests = collect_requests(inv,starttime,endtime)

        # Remove any for data we already have (requires db be updated)
        pruned_requests= prune_requests(requests, db_path)

        # Combine these into fewer (but larger) requests
        combined_requests = combine_requests(pruned_requests)

        # Add additional clients if user is requesting any restricted data
        waveform_clients= {'open':waveform_client}
        requested_networks = [ele[0] for ele in combined_requests]
        credentials = list(config['AUTH'].items())
        for ele in credentials:
            if ele[0].split('.')[0] not in requested_neworks:
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
                archive_request(request,waveform_clients,sds_path,db_path)
            except:
                print("Continous request not successful: ",request)


    # Now we can optionally clean up our database (stich continous segments, etc)
    print("\n ~~ Cleaning up database ~~")
    join_continuous_segments(db_path, gap_tolerance=float(config['PROCESSING']['gap_tolerance']))

    # And print the contents (first 100 elements), for now (DEBUG / TESTING feature)
    display_database_contents(db_path,100)


