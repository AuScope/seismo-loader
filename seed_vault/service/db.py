import sqlite3
import contextlib
import time
import random
import datetime
from pathlib import Path
from obspy import UTCDateTime
import pandas as pd
from typing import Union

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
        parent_dir = Path(db_path).parent
        parent_dir.mkdir(parents=True, exist_ok=True)
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
                # e_mag / earthquake magnitude
                # e_lat / earthquake origin latitude
                # e_lon / earthquake origin longitude
                # e_depth / earthquake depth (km)
                # e_time / earthquake origin time (utc)
                # s_netcode / station network code
                # s_stacode / station station code
                # s_lat / station latitude
                # s_lon / station longitude
                # s_elev / station elevation (km)
                # s_start / station start date (timestamp) * some scenarios where there are multiple stations at different times
                # s_end / station end date (timestamp) * NULL if station is still running
                # dist_deg / distance between event and station in degrees
                # dist_km / distance between event and station in km
                # azimuth / azimuth from EVENT to STATION
                # p_arrival / estimated p arrival at station (timestamp)
                # s_arrival / estimated S arrival at station (timestamp)
                # model / 1D earth model used in TauP
                # importtime / timestamp
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

    def join_continuous_segments(self, gap_tolerance=30):
        """
        Join continuous data segments in the database, even across day boundaries.
        
        :param gap_tolerance: Maximum allowed gap (in seconds) to still consider segments continuous
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Fetch all data sorted by network, station, location, channel, and starttime
            cursor.execute('''
                SELECT id, network, station, location, channel, starttime, endtime, importtime
                FROM archive_data
                ORDER BY network, station, location, channel, starttime
            ''')
            
            all_data = cursor.fetchall()
            
            to_delete = []
            to_update = []
            current_segment = None
            
            for row in all_data:
                id, network, station, location, channel, starttime, endtime, importtime = row
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
                        # Keep the latest importtime
                        current_segment[7] = max(importtime, current_segment[7]) ### bug if database was deleted and both are None
                        to_delete.append(id)
                    else:
                        # Start a new segment
                        to_update.append(tuple(current_segment))
                        current_segment = list(row)
            
            # Don't forget the last segment
            if current_segment:
                to_update.append(tuple(current_segment))
            
            # Perform updates
            cursor.executemany('''
                UPDATE archive_data
                SET endtime = ?, importtime = ?
                WHERE id = ?
            ''', [(row[6], row[7], row[0]) for row in to_update])
            
            # Delete the merged segments (break into pieces to avoid SQL3 limit)
            if to_delete:
                for i in range(0, len(to_delete), 500):
                    chunk = to_delete[i:i + 500]
                    cursor.executemany(
                        'DELETE FROM archive_data WHERE id = ?',
                        [(id,) for id in chunk]
                    )

        print(f"Joined segments. Deleted {len(to_delete)} rows, updated {len(to_update)} rows.")


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
    

    def execute_query(self, query: str) -> tuple[bool, Union[pd.DataFrame, str]]:
        """
        Execute any SQL query and return results along with a flag indicating if it's tabular data.
        
        Args:
            query (str): SQL query to execute
            
        Returns:
            tuple: (is_data: bool, result: Union[pd.DataFrame, str])
            - is_data: True if query returns tabular data, False otherwise
            - result: DataFrame for SELECT queries, status message for other queries
        """
        # List of SQL commands that modify data
        modify_commands = {'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE'}
        
        # Check if the query is a SELECT statement or a modify command
        first_word = query.strip().split()[0].upper()
        is_select = first_word == 'SELECT'
        has_error = False
        
        try:
            with self.connection() as conn:
                if is_select:
                    # For SELECT queries, return a DataFrame
                    df = pd.read_sql_query(query, conn)
                    return has_error, f"Query executed successfully. {len(df)} rows returned.", df
                else:
                    # For other queries, execute and return status message
                    cursor = conn.cursor()
                    cursor.execute(query)
                    
                    if first_word in modify_commands:
                        rows_affected = cursor.rowcount
                        return has_error, f"Query executed successfully. Rows affected: {rows_affected}", None
                    else:
                        return has_error, "Query executed successfully.", None
                    
        except Exception as e:
            error_message = f"Error executing query: {str(e)}"
            has_error = True
            return has_error, error_message, None
        

    def bulk_insert_archive_data(self, archive_list):
        if not archive_list:
            return 0

        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Add import time
            now = int(datetime.datetime.now().timestamp())
            archive_list = [tuple(list(ele) + [now]) for ele in archive_list if ele is not None]
            # Do the insert
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

            # Do the insert
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

    # expanded version of the above to include distances and azimth
    def fetch_arrivals_distances(self, event_id, netcode, stacode):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p_arrival, s_arrival, dist_km, dist_deg, azimuth 
                FROM arrival_data 
                WHERE event_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (event_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                return (result[0], result[1], result[2], result[3], result[4])
        return None



###### Legacy functions below
"""
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
            endtime TEXT,
            importtime REAL
            )
        ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_archive_data 
        ON archive_data (network, station, location, channel, starttime, endtime, importtime)
        ''')
    conn.commit()
    return

@contextlib.contextmanager
def safe_db_connection(db_path, max_retries=3, initial_delay=1):
    #Context manager for safe database connections with retry mechanism.
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
"""                
