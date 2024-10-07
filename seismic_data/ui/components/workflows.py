import streamlit as st
import plotly.express as px
import pandas as pd
from seismic_data.models.config import SeismoLoaderSettings
from seismic_data.ui.components.events import EventComponents
from seismic_data.ui.components.stations import StationComponents

from seismic_data.service.seismoloader import run_event
from seismic_data.service.waveform import stream_to_dataframe


class EventBasedWorkflow:

    settings: SeismoLoaderSettings
    stage: int = 1
    event_components: EventComponents
    station_components: StationComponents


    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.event_components = EventComponents(self.settings)    
        self.station_components = StationComponents(self.settings)    

    def next_stage(self):
        self.stage += 1
        st.rerun()

    def previous_stage(self):
        self.stage -= 1
        st.rerun()

    def render(self):
        if self.stage == 1:
            c1, c2, c3 = st.columns([1, 1, 1])        
            with c2:
                st.markdown("### Step 1: Select Events")
            with c1:
                if st.button("Next"):
                    self.event_components.map_component.df_events = self.event_components.event_select.sync_df_event_with_df_edit(
                        self.event_components.map_component.df_events
                    )
                    self.event_components.map_component.update_selected_catalogs()
                    if len(self.event_components.map_component.settings.event.selected_catalogs)>0 :                    
                        self.next_stage()   
                    else :
                        st.error("Please select an event to proceed to the next step.")
            self.event_components.render()

        if self.stage == 2:            
            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                if st.button("Next"):
                    self.station_components.map_component.df_stations = self.station_components.station_select.sync_df_station_with_df_edit(
                        self.station_components.map_component.df_stations
                    )
                    self.station_components.map_component.update_selected_inventories()
                    if len(self.station_components.map_component.settings.station.selected_invs)>0 :                    
                        self.next_stage()   
                    else :
                        st.error("Please select a station to proceed to the next step.")
            with c2:
                st.write("### Step 2: Select Stations")
            with c3:
                if st.button("Previous"):
                    self.previous_stage()                
            self.station_components.render(self.stage)

        if self.stage == 3:
            c1, c2, c3 = st.columns([1, 1, 1])
            with c2:
                st.write("### Step 3: Waveforms")
            with c3:
                if st.button("Previous"):
                    self.previous_stage()
            st.write(self.settings.event.selected_catalogs)
            st.write(self.settings.station.selected_invs)
            time_series = run_event(self.settings)
            df = pd.DataFrame(time_series)
            grouped = df.groupby(['Network', 'Station', 'Location'])
            for (network, station, location), group in grouped:
                with st.expander(f"Network: {network}, Station: {station}, Location: {location}"):
                    # with st.expander(f"Station: {station}"):
                    #     with st.expander(f"Location: {location}"):
                            # Assuming 'Data' column contains the timeseries data
                    all_data = pd.DataFrame()
                    for index, row in group.iterrows():
                        current_data = row['Data']
                        if not current_data.empty:
                            all_data = pd.concat([all_data, current_data])
                        else:
                            st.write(f"No data available for channel: {row['Channel']}")

                    # Now plot all channels on one plot
                    title = f'Waveform Data - {network}.{station}.{location}'
                    fig = px.line(all_data, x='time', y='amplitude', color='channel',
                                title=title)
                    st.plotly_chart(fig, use_container_width=True, key=f"event_waveform_{title}")


