"""
The events service should get the events based on a selection (filter) settings.
UI should generate the selection and pass it here. We need a single function
here that gets the selection and runs Rob's script.

We should also be able to support multi-select areas.

@TODO: For now, dummy scripts are used. @Yunlong to fix.
"""

import pandas as pd
import streamlit as st
import requests

from seismic_data.models.events import EventFilter



def convert_filter_to_cfg(event_filter: EventFilter):
    """
    @TODO: @Yunlong, this method should basically, convert event_filter
    to a CFG object required as an input by Rob's scripts.
    """
    pass


@st.cache_data
def get_event_data(event_filter_dict: dict):
    """
    @TODO: @Yunlong, This should basically convert event_filter and call Rob's script.
    For now, dummy example is used.

    Note: streamlit is not able to Hash complex class object. Hence, the input to
    the function is dictionary.
    """
    event_filter = EventFilter(**event_filter_dict)
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query"
        "?format=geojson"
        f"&starttime={event_filter.start_date}"
        f"&endtime={event_filter.end_date}"
        f"&minmagnitude={event_filter.min_magnitude}"
        f"&maxmagnitude={event_filter.max_magnitude}"
        f"&mindepth={event_filter.min_depth}"
        f"&maxdepth={event_filter.max_depth}"
    )
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        st.error(f"Failed to fetch data: {response.status_code}")
        return None

def event_response_to_df(data):
    """
    @TODO: base on response from FSDN, below should be re-written
    """
    features = data['features']
    records = []
    for feature in features:
        properties = feature['properties']
        geometry = feature['geometry']['coordinates']
        record = {
            'place': properties['place'],
            'magnitude': properties['mag'],
            'time': pd.to_datetime(properties['time'], unit='ms'),
            'longitude': geometry[0],
            'latitude': geometry[1],
            'depth': geometry[2]
        }
        records.append(record)
    return pd.DataFrame(records)