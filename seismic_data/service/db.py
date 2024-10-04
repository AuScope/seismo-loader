import sqlite3
import contextlib


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