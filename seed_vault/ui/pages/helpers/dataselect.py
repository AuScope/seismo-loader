import streamlit as st
import os
import sqlite3
from obspy.clients.fdsn import Client
from obspy import UTCDateTime
import pandas as pd
import matplotlib.pyplot as plt
from obspy.geodetics.base import locations2degrees
from obspy.taup import TauPyModel


from seed_vault.service.seismoloader import (
    setup_database,
    collect_requests,
    prune_requests,
    combine_requests,
    archive_request,
    join_continuous_segments,
    display_database_contents,
)
st.set_page_config(layout="wide")
st.title("SeismoLoader Streamlit App")

# Sidebar for configuration
st.sidebar.header("Configuration")
sds_path = st.sidebar.text_input("SDS Path", "./data/SDS")
db_path = st.sidebar.text_input("Database Path", "./data/database.sql")

# Main app
if st.button("Setup Database"):
    if not os.path.exists(db_path):
        setup_database(db_path)
        st.success("Database setup complete!")
    else:
        st.warning("Database already exists.")

# client setup
client_name = st.selectbox("Select FDSN Client", ["IRIS", "AUSPASS", "GEOFON"])
client = Client(client_name)

# Data download options
download_type = st.radio("Download Type", ["Continuous", "Event"])

if download_type == "Continuous":
    st.subheader("Continuous Data Download")
    start_time = st.date_input("Start Date")
    end_time = st.date_input("End Date")
    network = st.text_input("Network", "*")
    station = st.text_input("Station", "*")
    location = st.text_input("Location", "*")
    channel = st.text_input("Channel", "*")

    if st.button("Download Continuous Data"):
        start_time = UTCDateTime(start_time)
        end_time = UTCDateTime(end_time)

        inv = client.get_stations(
            network=network,
            station=station,
            location=location,
            channel=channel,
            starttime=start_time,
            endtime=end_time,
            level="channel",
        )

        requests = collect_requests(inv, start_time, end_time)
        pruned_requests = prune_requests(requests, db_path)
        combined_requests = combine_requests(pruned_requests)

        progress_bar = st.progress(0)
        for i, request in enumerate(combined_requests):
            archive_request(request, client, sds_path, db_path)
            progress_bar.progress((i + 1) / len(combined_requests))

        st.success("Continuous data download complete!")

elif download_type == "Event":
    st.subheader("Event-Based Data Download")
    event_start_time = st.date_input("Event Start Date")
    event_end_time = st.date_input("Event End Date")
    min_magnitude = st.number_input("Minimum Magnitude", value=6.0)

    if st.button("Download Event Data"):
        event_start_time = UTCDateTime(event_start_time)
        event_end_time = UTCDateTime(event_end_time)

        cat = client.get_events(
            starttime=event_start_time,
            endtime=event_end_time,
            minmagnitude=min_magnitude,
        )

        inv = client.get_stations(
            network="*",
            station="*",
            channel="BH?",
            starttime=event_start_time,
            endtime=event_end_time,
            level="channel",
        )

        ttmodel = TauPyModel()

        progress_bar = st.progress(0)
        for i, eq in enumerate(cat):
            requests = collect_requests_event(
                eq,
                inv,
                min_dist_deg=30,
                max_dist_deg=90,
                before_p_sec=10,
                after_p_sec=120,
                model=ttmodel,
            )
            pruned_requests = prune_requests(requests, db_path)
            combined_requests = combine_requests(pruned_requests)

            for request in combined_requests:
                archive_request(request, client, sds_path, db_path)

            progress_bar.progress((i + 1) / len(cat))

        st.success("Event data download complete!")

# Here is for database operations
if st.button("Join Continuous Segments"):
    join_continuous_segments(db_path, gap_tolerance=60)
    st.success("Continuous segments joined successfully!")

if st.button("Display Database Contents"):
    contents = display_database_contents(db_path, 100)
    st.write(contents)
