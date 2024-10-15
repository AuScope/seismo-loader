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

from seismic_data.models.config import SeismoLoaderSettings
from seismic_data.service.seismoloader import get_events


# @st.cache_data
# def get_event_data(settings_json_str: str):

#     settings = SeismoLoaderSettings.model_validate_json(settings_json_str)
#     return get_events(settings)


# @st.cache_data
def get_event_data(settings: SeismoLoaderSettings):
    return get_events(settings)


def event_response_to_df(data):
    """
    @TODO: base on response from FSDN, below should be re-written
    """
    records = []
    for event in data:
        # Extract the preferred origin (location info)
        origin = event.preferred_origin() or event.origins[0]
        magnitude = event.preferred_magnitude() or event.magnitudes[0]
        
        # Extract location (longitude, latitude, depth)
        longitude = origin.longitude
        latitude = origin.latitude
        depth = origin.depth / 1000  # Convert depth to kilometers

        # Extract the time and place
        time = origin.time.datetime
        place = event.event_descriptions[0].text if event.event_descriptions else "Unknown place"
        
        # Extract the magnitude
        mag = magnitude.mag

        # Create the record dictionary
        record = {
            'place': place,
            'magnitude': mag,
            'time': pd.to_datetime(time),  # Convert to pandas datetime
            'longitude': longitude,
            'latitude': latitude,
            'depth': depth  # in kilometers
        }
        
        records.append(record)
    return pd.DataFrame(records)