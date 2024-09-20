import streamlit as st
from datetime import datetime, timedelta
from seismic_data.models.config import SeismoLoaderSettings

# Sidebar date input

def station_filter_menu(settings: SeismoLoaderSettings, key: str):
    # tab1, tab2 = st.sidebar.tabs(["Filter state", "Station"])
    settings.station.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=1), key=f"{key}-start_time")
    settings.station.date_config.end_time = st.date_input("End Date", datetime.now(), key=f"{key}-end_time")

    if settings.station.date_config.start_time > settings.station.date_config.end_time:
        st.error("Error: End Date must fall after Start Date.")
    
    return settings

    


