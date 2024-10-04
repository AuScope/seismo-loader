import pandas as pd
import os
import obspy
from obspy import UTCDateTime

from seismic_data.models.config import SeismoLoaderSettings, SeismoQuery
from seismic_data.service.db import safe_db_connection

def stream_to_dataframe(stream):
    df = pd.DataFrame()
    for trace in stream:
        data = {
            'time': trace.times("matplotlib"),  # Times in days since '0001-01-01'
            'amplitude': trace.data,
            'channel': trace.stats.channel
        }
        trace_df = pd.DataFrame(data)
        # Adjust origin to '1970-01-01' to avoid overflow
        trace_df['time'] = pd.to_datetime(trace_df['time'], unit='D', origin=pd.Timestamp('1970-01-01'))
        df = pd.concat([df, trace_df], ignore_index=True)
    return df


def check_downloaded(cursor, req: SeismoQuery): # network, station, location, channel, starttime, endtime):
    query = '''
    SELECT COUNT(*) FROM downloads WHERE
    network = ? AND
    station = ? AND
    location = ? AND
    channel = ? AND
    starttime <= ? AND
    endtime >= ?
    '''
    cursor.execute(query, (req.network, req.station, req.location, req.channel, req.starttime.isoformat(), req.endtime.isoformat()))
    result = cursor.fetchone()
    return result[0] > 0


def construct_path(base_dir, req: SeismoQuery, year):
    """
    Construct the path based on given parameters.
    """
    # Ensure the channel name is split if it includes the type (e.g., 'BH1.D' should be split into 'BH1' for directory)
    channel_dir = req.channel.split('.')[0]
    return os.path.join(base_dir, str(year), req.network, req.station, channel_dir)

def find_files_for_timespan(settings: SeismoLoaderSettings, network, station, location, channel, start, end):
    """
    Find all files that intersect with the requested time span.
    @TODO: once db.py completed, complete this.
    """
    files_to_read = []
    with safe_db_connection(settings.db_path) as conn:
        cursor = conn.cursor()
        if check_downloaded(cursor):
            current_date = start
            while current_date <= end:
                year = current_date.year
                day = current_date.julday
                directory = construct_path(settings.sds_path, network, station, channel, year)
                filename_pattern = f"{network}.{station}.{location}.{channel}.{year}.{day:03d}"
                
                for filename in os.listdir(directory):
                    if filename.startswith(filename_pattern):
                        file_path = os.path.join(directory, filename)
                        file_start = UTCDateTime(year, julday=day)
                        file_end = file_start + 86400  # Assuming one file per day
                        if file_start <= end and file_end >= start:
                            files_to_read.append(file_path)
                
                current_date += 86400  # Move to the next day

    return files_to_read

def read_and_combine_waveforms(files, start, end):
    """
    Read and combine waveform data from a list of files.
    """
    stream = obspy.Stream()
    for file in files:
        st = obspy.read(file, starttime=start, endtime=end)
        stream += st
    return stream