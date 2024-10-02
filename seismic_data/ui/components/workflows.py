import streamlit as st
from seismic_data.models.config import SeismoLoaderSettings
from seismic_data.ui.components.events import EventComponents
from seismic_data.ui.components.stations import StationComponents

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
                if st.button("Previous"):
                    self.previous_stage()
            with c2:
                st.write("### Step 2: Select Stations")
            with c3:
                if st.button("Next"):
                    self.station_components.map_component.df_stations = self.station_components.station_select.sync_df_station_with_df_edit(
                        self.station_components.map_component.df_stations
                    )
                    self.station_components.map_component.update_selected_inventories()
                    if len(self.station_components.map_component.settings.station.selected_invs)>0 :                    
                        self.next_stage()   
                    else :
                        st.error("Please select a station to proceed to the next step.")
            self.station_components.render(self.stage)
