import pandas as pd
import os
import obspy
from obspy import UTCDateTime
from obspy.clients.filesystem.sds import Client as LocalClient

from seed_vault.models.config import SeismoLoaderSettings, SeismoQuery
from seed_vault.models.exception import NotFoundError

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


def check_is_archived(cursor, req: SeismoQuery): 
    cursor.execute('''
        SELECT starttime, endtime FROM archive_data
        WHERE network = ? AND station = ? AND location = ? AND channel = ?
        AND endtime >= ? AND starttime <= ?
        ORDER BY starttime
    ''', (req.network, req.station, req.location, req.channel, req.starttime.isoformat(), req.endtime.isoformat()))
    
    existing_data = cursor.fetchall()
    if not existing_data:
        return False
    return True

#this is a simpler version.. if the data doesn't exist it just returns an empty stream
def get_local_waveform(req: SeismoQuery, settings: SeismoLoaderSettings):
    client = LocalClient(settings.sds_path)
    st = client.get_waveforms(network=req.network,station=req.station,
                            location=req.location,channel=req.channel,
                            starttime=UTCDateTime(req.starttime),endtime=UTCDateTime(req.endtime))
    if not st:
        raise NotFoundError("Not Found: the requested data was not found in local archived database.")
    return st
