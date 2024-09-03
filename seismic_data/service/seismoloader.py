#!/usr/bin/env python3

# frankenstein CLI SDS data downloader/archiver/database management, use: $ ./seismoloader.py example.cfg

#requirements: obspy, tqdm, sqlite3, maybe something else im forgetting

# ver 0.2 Aug24

import os
import sys
import time
import sqlite3
import datetime
import multiprocessing
import configparser
from tqdm import tqdm

import obspy
from obspy.clients.fdsn import Client
from obspy.geodetics.base import locations2degrees
from obspy import UTCDateTime
from obspy.taup import TauPyModel

def read_config(config_file):
    config = configparser.ConfigParser()
    config.read(config_file)
    return config

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
    
    # Process files with or without multiprocessing (currently having issues with OSX and undoubtably windows is going to be a bigger problem)
    if num_processes > 1:
        try:
            with multiprocessing.Pool(processes=num_processes) as pool:
                results = list(tqdm(pool.imap(process_file, file_paths), total=total_files, desc="Processing files"))
        except Exception as e:
            print(f"Multiprocessing failed: {str(e)}. Falling back to single-process execution.")
            num_processes = 1
    if num_processes == 1:
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


from tabulate import tabulate #non-standard!!
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


# this is for requests for ~continuous data
def collect_requests(inv, time0, time1, days_per_request=5):
    """ Collect all requests required to download everything in inventory, split into 5-day periods """
    requests = []  # network, station, location, channel, starttime, endtime

    for net in inv:
        for sta in net:
            for cha in sta:
                start_date = max(time0, cha.start_date.date)
                end_date = min(time1 - (1/cha.sample_rate), cha.end_date.date + datetime.timedelta(days=1))
                
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

# this is for requests for shorter, event-based data
def get_p_s_times(eq,sta_lat,sta_lon,ttmodel=ttmodel):
    eq_lat = eq.origins[0].latitude
    eq_lon = eq.origins[0].longitude
    eq_depth = eq.origins[0].depth / 1000 #check this
    dist_deg = locations2degrees(sta_lat,sta_lon,eq_lat,eq_lon) #probably already calculated at this stage

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
    
    # TBH we aren't really concerned with S arrivals, but while we're here, may as well.
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
        #need to quickly replace all "None" ends with some high number
        for cha in sta.channels:
            if cha.end_date is None: cha.end_date = UTCDateTime(2099,1,1)
        CHs = set([tr.stats.channel[0:2] for tr in st])
        for ch in cha_rank:
            selection = [ele for ele in sta.channels if ele.code[0:2] == ch and ele.start_date <= t <= ele.end_date]
            if selection: return selection
        print("no valid channels found in output_best_channels")
        return []

def collect_requests_event(eq,inv,min_dist_deg=30,max_dist_deg=90,before_p_sec=10,after_p_sec=120,model=ttmodel):
    """ collect all requests for data in inventory for given event eq """

    # n.b. "eq" is an earthquake object, e.g. one element of the array collected in a "catalog" object

    origin = eq.origins[0] # default to the primary I suppose
    ot = origin.time
    sub_inv = inv.select(time = ot) # loose filter to select only stations that were ON during the earthquake

    # TODO: further filter by selecting best available channels

    requests_per_eq = []
    for net in sub_inv:
        for sta in net:
            dist_deg = locations2degrees(sta.latitude,sta.longitude,origin.latitude,origin.longitude)
            if dist_deg < min_dist_deg or dist_deg > max_dist_deg:
                continue
            p_time, s_time = get_p_s_times(eq,sta.latitude,sta.longitude)
            if not p_time: continue # need error msg also TODO

            t_start = p_time - abs(before_p_sec)
            t_end = p_time + abs(after_p_sec)

            for cha in sta: #will have to had filtered channels prior to this, else will grab them all
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
    """ combine requests to 
    1) minimize how many and 
    2) not include data already present in our database
       (unless intentionally overwriting) 
    requests can be combined for multiple stations/channels by comma separation BHZ,BHN,BHE
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

def prune_requests(requests, db_path):
    """ remove any overlapping requests where already-archived data (via db_path) may exist """
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
                    
                    if current_time < db_start:
                        # There's a gap before this existing data
                        pruned_requests.append((network, station, location, channel, 
                                                current_time.isoformat(), db_start.isoformat()))
                    
                    current_time = max(current_time, db_end)
                
                if current_time < end_time:
                    # There's a gap after the last existing data
                    pruned_requests.append((network, station, location, channel, 
                                            current_time.isoformat(), end_time.isoformat()))
    
    return pruned_requests

def archive_request(request,client,sds_path,db_path):
    """ send a request to an FDSN center, parse it, save to archive, and update our database """
    try:
        st = client.get_waveforms(network=request[0], station=request[1],
                                  location=request[2], channel=request[3],
                                  starttime=UTCDateTime(request[4]),endtime=UTCDateTime(request[5]))
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
                print("merging ", full_path)
            else:
                # If file doesn't exist, simply write the new data
                day_tr.write(full_path, format="MSEED", reclen=4096, encoding='STEIM2')
                print("writing ", full_path)

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
        print("Usage: python database_sync.py input.cfg")
        sys.exit(1)
    
    config_file = sys.argv[1]
    try:
        config = read_config(config_file)
    except:
        print("cannot read configuration file", config_file)
        sys.exit(1)

    sds_path = config['SDS']['sds_path']
    db_path = config['DATABASE']['db_path']
    if not db_path:
        db_path = os.path.join(sds_path,"database.sql")

    #setup SDS directory
    if not os.path.exists(sds_path):
        os.makedirs(sds_path)

    #setup database
    if not os.path.exists(db_path):
        setup_database(db_path)

    download_type = config['PROCESSING']['download_type'].lower()
    if download_type not in ['continuous','event']:
        download_type = 'continuous'

    if download_type == 'continuous':
        starttime = UTCDateTime(config['STATIONSEARCH']['starttime'])
        endtime = UTCDateTime(config['STATIONSEARCH']['endtime'])

    else: #assume "event"
        starttime = UTCDateTime(config['EVENTS']['starttime'])
        endtime = UTCDateTime(config['EVENTS']['endtime'])

    client = Client(config['FDSN']['clients'])

    # if user is specifying / filtering, use these
    net = config['STATIONSEARCH']['network']
    if not net:
        net = '*'
    sta = config['STATIONSEARCH']['station']
    if not sta:
        sta = '*'
    loc = config['STATIONSEARCH']['location']
    if not loc:
        loc = '*'
    cha = config['STATIONSEARCH']['channel']
    if not cha:
        cha = '*'

    if config['STATIONSEARCH']['geo_constraint'].lower() == 'bounding':
        ## test if all variables exist / error if not
        inv = client.get_stations(network=net,station=sta,location=loc,channel=cha,starttime=starttime,endtime=endtime,
            minlatitude=float(config['STATIONSEARCH']['minlatitude']),
            maxlatitude=float(config['STATIONSEARCH']['maxlatitude']),
            minlongitude=float(config['STATIONSEARCH']['minlongitude']),
            maxlongitude=float(config['STATIONSEARCH']['maxlongitude']),
            includerestricted=config['STATIONSEARCH']['includerestricted'],
            level='channel'
            )
    elif config['STATIONSEARCH']['geo_constraint'].lower() == 'circle':
        ## test if all variables exist / error if not
        inv = client.get_stations(network=net,station=sta,location=loc,channel=cha,starttime=starttime,endtime=endtime,
            latitude=float(config['STATIONSEARCH']['latitude']),
            longitude=float(config['STATIONSEARCH']['longitude']),
            minradius=float(config['STATIONSEARCH']['minradius']),           
            maxradius=float(config['STATIONSEARCH']['maxradius']),
            includerestricted=config['STATIONSEARCH']['includerestricted'],
            level='channel'
            )

    else: #no geographic constraint
        inv = client.get_stations(network=net,stations=sta,location=loc,channel=cha,starttime=starttime,endtime=endtime)

    #now remove unwanted stations or networks, and manually add anything else we were told to manually add (TODO)

    if config['PROCESSING']['download_type'].lower() == 'event':
        ttmodel = TauPyModel(config['PROCESSING']['model'])
        print("event processing not coded yet!")
    else:
        # collect requests
        requests = collect_requests(inv,starttime,endtime)

        # remove any for data we already have (requires db be updated)
        pruned_requests= prune_requests(requests, db_path)

        # combine these into fewer (but larger) requests
        combined_requests = combine_requests(pruned_requests)

        # archive to disk and updated database
        for request in combined_requests:
            try: 
                archive_request(request,client,sds_path,db_path)
            except:
                print("request not successful: ",request)


    #now we can optionally clean up our database (stich continous segments, etc)
    print("cleaning up database...")
    join_continuous_segments(db_path, gap_tolerance=float(config['PROCESSING']['gap_tolerance']))

    # and print the contents (first 100 elements), for now
    display_database_contents(db_path,100)






################################################################# scratch/testing
print("stopping here...")
stophere[0] = 0

#####################################################
#    OK let's test this out a little. 
#    Ideally most of this could be input from a .cfg file to enable CLI-only interface if needed

#first lets's search for data within these parameters
server = 'AUSPASS'
from obspy.clients.fdsn import Client
client = Client(server)

sds_path = "./testSDS"
db_path = sds_path + "/database.sql" #a good default... place it in the root SDS folder

## (set up files/paths)

if not os.path.exists(db_path):
    setup_database(db_path)


target_lat = -31
target_lon = 125.4
maxR = 0.3 #degrees
time0 = UTCDateTime(2014,1,1)
time1 = UTCDateTime(2014,1,15)


#this is essentially our search engine (but it doesn't filter time!)
inv = client.get_stations(latitude=target_lat,longitude=target_lon,channel='?HZ',
                          maxradius=maxR,starttime=time0,endtime=time1,level='channel')

########now that we have a list of stations we want (inv), let's calculate the requests needed to get them

requests = collect_requests(inv,time0,time1)

# remove any for data we already have (requires db be updated)
pruned_requests= prune_requests(requests, db_path)

# combine these into fewer (but larger) requests
combined_requests = combine_requests(pruned_requests)


for request in combined_requests:
    archive_request(request,client,sds_path,db_path) #db_path currently not being updated in this function (TODO)

#for now sync our db separately
populate_database_from_sds(sds_path,db_path,1)

# clean up a smidge
join_continuous_segments(db_path, gap_tolerance=60)

######## now let's try again, but with both N and Z channels. the Z should be skipped (via prine_requests) since we already downloaded it and it's in the database
inv = client.get_stations(latitude=target_lat,longitude=target_lon,channel='?HZ,?HN',
                          maxradius=maxR,starttime=time0,endtime=time1,level='channel')

requests = collect_requests(inv,time0,time1)

pruned_requests= prune_requests(requests, db_path)

combined_requests = combine_requests(pruned_requests)



for request in combined_requests:
    archive_request(request,client,sds_path,db_path) #db_path currently not being updated in this function (TODO)

#for now sync our db separately
populate_database_from_sds(sds_path,db_path,1)

# clean up a smidge
join_continuous_segments(db_path, gap_tolerance=60)


################ OK let's add some EVENT data! we now need TWO searches 1) station (inv) and 2) earthquakes (cat)
inv = client.get_stations(latitude=target_lat,longitude=target_lon,channel='?HZ,?HN,?HE',
                          maxradius=maxR,starttime=time0,endtime=time1,level='channel') #now includes E channel
cat = client.get_events(latitude=target_lat,longitude=target_lon,minradius=30,maxradius=90,
                        minmagnitude=6,starttime=time0,endtime=time1) # returns just 1 event but can return thousands!

#n.b. the code currently separates each event... should probably change so that cat is input and it loops within
for eq in cat:
    print("running eq %s", eq.origins[0].time)
    requests = collect_requests_event(eq,inv,min_dist_deg=30,max_dist_deg=90,before_p_sec=10,after_p_sec=120,model=ttmodel)
    pruned_requests = prune_requests(requests, db_path)
    combined_requests = combine_requests(pruned_requests)
    for request in combined_requests:
        archive_request(request,client,sds_path,db_path)


#to see what's in our database:
display_database_contents(db_path,150)


###### let's try adding another FAKE event which is on the same day, but an hour before. now files should be appended without being replaced
eq_fake = eq.copy()
eq_fake.origins[0].time = eq_fake.origins[0].time - 3600

requests = collect_requests_event(eq_fake,inv,min_dist_deg=30,max_dist_deg=90,before_p_sec=10,after_p_sec=120,model=ttmodel)
pruned_requests = prune_requests(requests, db_path)
combined_requests = combine_requests(pruned_requests)
for request in combined_requests:
    archive_request(request,client,sds_path,db_path)



#### now what's the point of all this??? well, you can now use your "local" SDS archive as a personal server!
if 1 == 2:
    from obspy.clients.filesystem.sds import Client as SDS_Client

    sds_server = SDS_Client(sds_path)
    st = sds_server.get_waveforms("blah blah blah")

    #otherwise people can figure their own way out or restructure however they like






