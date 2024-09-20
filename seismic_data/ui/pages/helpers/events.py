import streamlit as st
from datetime import datetime, timedelta
from seismic_data.models.events import EventFilter

# Sidebar date input

def event_filter_menu(event_filter: EventFilter):
    st.sidebar.header("Select Date Range")
    tab1, tab2 = st.sidebar.tabs(["Filter state", "Station"])
    with tab1:
        event_filter.start_date = st.date_input("Start Date", datetime.now() - timedelta(days=1))
        event_filter.end_date = st.date_input("End Date", datetime.now())

        if event_filter.start_date > event_filter.end_date:
            st.error("Error: End Date must fall after Start Date.")

        st.header("Filter Earthquakes")
        event_filter.min_magnitude = st.slider("Min Magnitude", min_value=-2.0, max_value=10.0, value=2.4, step=0.1)
        event_filter.max_magnitude = st.slider("Max Magnitude", min_value=-2.0, max_value=10.0, value=10.0, step=0.1)
        event_filter.min_depth = st.slider("Min Depth (km)", min_value=-5.0, max_value=800.0, value=0.0, step=1.0)
        event_filter.max_depth = st.slider("Max Depth (km)", min_value=-5.0, max_value=800.0, value=200.0, step=1.0)


    return event_filter

    


