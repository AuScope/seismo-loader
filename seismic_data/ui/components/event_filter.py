import streamlit as st
from datetime import datetime, timedelta
from seismic_data.models.config import SeismoLoaderSettings

# Sidebar date input

def event_filter_menu(settings: SeismoLoaderSettings, key: str):
    # tab1, tab2 = st.sidebar.tabs(["Filter state", "Station"])
    settings.event.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=1), key=f"{key}-start_time")
    settings.event.date_config.end_time = st.date_input("End Date", datetime.now(), key=f"{key}-end_time")

    if settings.event.date_config.start_time > settings.event.date_config.end_time:
        st.error("Error: End Date must fall after Start Date.")

    st.header("Filter Earthquakes")
    settings.event.min_magnitude, settings.event.max_magnitude = st.slider("Min Magnitude", min_value=-2.0, max_value=10.0, value = (2.4,9.0), step=0.1, key=f"{key}-mag")
    # settings.max_magnitude = st.slider("Max Magnitude", min_value=-2.0, max_value=10.0, value=10.0, step=0.1)
    settings.event.min_depth, settings.event.max_depth = st.slider("Min Depth (km)", min_value=-5.0, max_value=800.0, value=(0.0,500.0), step=1.0, key=f"{key}-depth")
    # settings.max_depth = st.slider("Max Depth (km)", min_value=-5.0, max_value=800.0, value=200.0, step=1.0)

    return settings

    


