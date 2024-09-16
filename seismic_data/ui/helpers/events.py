import streamlit as st
from datetime import datetime, timedelta
from seismic_data.models.events import EventFilter

# Sidebar date input

def event_filter_menu(event_filter: EventFilter):
    st.sidebar.header("Select Date Range")
    event_filter.start_date = st.sidebar.date_input("Start Date", datetime.now() - timedelta(days=1))
    event_filter.end_date = st.sidebar.date_input("End Date", datetime.now())

    if event_filter.start_date > event_filter.end_date:
        st.sidebar.error("Error: End Date must fall after Start Date.")

    st.sidebar.header("Filter Earthquakes")
    event_filter.min_magnitude = st.sidebar.slider("Min Magnitude", min_value=0.0, max_value=10.0, value=2.4, step=0.1)
    event_filter.max_magnitude = st.sidebar.slider("Max Magnitude", min_value=0.0, max_value=10.0, value=10.0, step=0.1)
    event_filter.min_depth = st.sidebar.slider("Min Depth (km)", min_value=0.0, max_value=250.0, value=0.0, step=1.0)
    event_filter.max_depth = st.sidebar.slider("Max Depth (km)", min_value=0.0, max_value=250.0, value=200.0, step=1.0)


    return event_filter

    


