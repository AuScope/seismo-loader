import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from datetime import datetime, timedelta


from seismic_data.models.events import EventFilter
from seismic_data.service.events import get_event_data, event_response_to_df
from seismic_data.ui.helpers.map import create_map, add_data_points
from seismic_data.ui.helpers.events import event_filter_menu

st.set_page_config(layout="wide")


def handle_get_events(base_map, event_filter: EventFilter):
    # GET DATA
    data = get_event_data(event_filter.model_dump())     
    components = {}
    if data:
        df = event_response_to_df(data)
        total_earthquakes = len(df)
        
        components['subheader'] = f"Showing {total_earthquakes} events"
        
        if not df.empty:
            base_map = add_data_points(base_map, df, col_color='magnitude')
            components['dataframe'] = df
        else:
            components['warning'] = "No earthquakes found for the selected magnitude and depth range."
    else:
        components['error'] = "No data available."

    components['map'] = base_map
    return components



def main():
    # INIT event_filter object
    event_filter = EventFilter()

    # INIT side menu
    event_filter = event_filter_menu(event_filter)

    # INIT MAP  
    if 'event_map' not in st.session_state:
        st.session_state.event_map = {'map': create_map()}

    # INIT Button
    clicked = st.button("Get Events")

    # INIT Layout
    c1, c2 = st.columns([2,1])
    

    # Handle Button Clicked
    if clicked:
        st.session_state.event_map = {'map': create_map()}
        st.session_state.event_map = handle_get_events(st.session_state.event_map.get('map'), event_filter)

    if 'subheader' in st.session_state['event_map']:
        st.subheader(st.session_state['event_map']['subheader'])
    if 'dataframe' in st.session_state['event_map']:
        st.dataframe(st.session_state['event_map']['dataframe'])
    if 'warning' in st.session_state['event_map']:
        st.warning(st.session_state['event_map']['warning'])
    if 'error' in st.session_state['event_map']:
        st.error(st.session_state['event_map']['error'])

    with c1:
        # output = create_card("Events", st_folium, st_map, use_container_width=True)
        output = st_folium(st.session_state.event_map.get('map'), use_container_width=True)
    with c2:
        st.write(output)

if __name__ == "__main__":
    main()
