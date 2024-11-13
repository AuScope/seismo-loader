from seed_vault.ui.components.waveform import WaveformComponents
import streamlit as st
import plotly.express as px
import pandas as pd

from seed_vault.enums.ui import Steps
from seed_vault.models.config import SeismoLoaderSettings, DownloadType, WorkflowType
from seed_vault.service.seismoloader import get_selected_stations_at_channel_level

from seed_vault.ui.components.base import BaseComponent
from seed_vault.ui.pages.helpers.common import get_app_settings

download_options = [f.name.title() for f in DownloadType]

workflow_options = {workflow.value: workflow for workflow in WorkflowType}
workflow_options_list = list(workflow_options.keys())


class CombinedBasedWorkflow:
    settings: SeismoLoaderSettings
    stage: int = 0
    event_components: BaseComponent
    station_components: BaseComponent
    waveform_components: WaveformComponents

    def __init__(self):
        self.settings = get_app_settings()
        self.event_components = BaseComponent(self.settings, step_type=Steps.EVENT, prev_step_type=None, stage=1)    
        self.station_components = BaseComponent(self.settings, step_type=Steps.STATION, prev_step_type=Steps.EVENT, stage=2)    
        self.waveform_components = WaveformComponents(self.settings)


    def next_stage(self):
        self.stage += 1
        st.rerun()

    def previous_stage(self):
        self.stage -= 1
        st.rerun()

    
    def init_settings(self, selected_flow_type):
        """
        See description in render_stage_0.
        """
        # if (
        #     'selected_flow_type' in st.session_state and
        #     st.session_state.selected_flow_type == selected_flow_type
        # ):
        #     return False        
        
        self.settings = get_app_settings()
        st.session_state["show_error"] = False
        st.session_state["error_message"] = ""

        st.session_state.selected_flow_type = selected_flow_type
        # return True
        


    def render_stage_0(self):
        """
        ToDo: We probably need a settings clean up in this stage,
        to ensure if user changes Flow Type, geometry selections and
        selected events + stations are cleaned for a fresh start of a 
        new flow. Probably, we only need the clean up, if Flow Type selection
        changes. Also, probably, we do not need clean up on the filter settings 
        (we actually may need to keep the filters as is).
        """
        c1, c2 = st.columns([1,2])
        # with c1:
        #     st.write("## Select the Seismic Data Request Flow")
        # with c2:
        with c1:
            selected_flow_type = st.selectbox(
                "Select the Seismic Data Request Flow", 
                workflow_options_list, 
                index=workflow_options_list.index(self.settings.selected_workflow.value), 
                key="combined-pg-download-type",
            )
            self.init_settings(selected_flow_type)
            if selected_flow_type:
                self.settings.selected_workflow = workflow_options[selected_flow_type]

        with c2:
            st.text("")
            if st.button("Start"):
                st.session_state.selected_flow_type = selected_flow_type
                self.settings.set_download_type_from_workflow()
                if self.settings.selected_workflow == WorkflowType.EVENT_BASED:
                    self.event_components = BaseComponent(self.settings, step_type=Steps.EVENT, prev_step_type=None, stage=1)    
                    self.station_components = BaseComponent(self.settings, step_type=Steps.STATION, prev_step_type=Steps.EVENT, stage=2)    
                    self.waveform_components = WaveformComponents(self.settings)

                if self.settings.selected_workflow == WorkflowType.STATION_BASED:
                    self.station_components = BaseComponent(self.settings, step_type=Steps.STATION, prev_step_type=None, stage=1)   
                    self.event_components = BaseComponent(self.settings, step_type=Steps.EVENT, prev_step_type=Steps.STATION, stage=2)  
                    self.waveform_components = WaveformComponents(self.settings)

                if self.settings.selected_workflow == WorkflowType.CONTINUOUS:
                    self.station_components = BaseComponent(self.settings, step_type=Steps.STATION, prev_step_type=None, stage=1)
                    self.waveform_components = WaveformComponents(self.settings)

                self.next_stage()

        st.info(self.settings.selected_workflow.description)



    def trigger_error(self, message):
        """Set an error message in session state to be displayed."""
        st.session_state["show_error"] = True
        st.session_state["error_message"] = message

    def validate_and_adjust_selection(self, workflow_type):
        """Validate selection based on workflow type and return True if valid, else trigger error."""

        if self.stage == 1:
            if workflow_type == WorkflowType.EVENT_BASED:
                self.event_components.sync_df_markers_with_df_edit()
                self.event_components.update_selected_data()
                selected_catalogs = self.event_components.settings.event.selected_catalogs
                if selected_catalogs is None or len(selected_catalogs) <= 0:
                    self.trigger_error("Please select an event to proceed to the next step.")
                    return False
            elif workflow_type in [WorkflowType.STATION_BASED, WorkflowType.CONTINUOUS]:
                self.station_components.sync_df_markers_with_df_edit()
                self.station_components.update_selected_data()
                selected_invs = self.station_components.settings.station.selected_invs
                if selected_invs is None or len(selected_invs) <= 0:
                    self.trigger_error("Please select a station to proceed to the next step.")
                    return False
                
                self.settings.waveform.client = self.settings.station.client                        
                
                # Apply the additional settings adjustment for CONTINUOUS workflow
                if workflow_type == WorkflowType.CONTINUOUS:
                    self.settings = get_selected_stations_at_channel_level(self.settings)

        if self.stage == 2:
            if workflow_type == WorkflowType.EVENT_BASED: 
                self.station_components.sync_df_markers_with_df_edit()
                self.station_components.update_selected_data()
                selected_invs = self.station_components.settings.station.selected_invs
                if selected_invs is not None and len(selected_invs) > 0: 
                    self.settings.waveform.client = self.settings.station.client                           
                    self.settings = get_selected_stations_at_channel_level(self.settings)                                   
                else:
                    self.trigger_error("Please select a station to proceed to the next step.")
                    return False

            elif workflow_type == WorkflowType.STATION_BASED:
                self.event_components.sync_df_markers_with_df_edit()
                self.event_components.update_selected_data()
                selected_catalogs = self.event_components.settings.event.selected_catalogs
                if selected_catalogs is not None and len(selected_catalogs)>0 :                        
                    self.settings = get_selected_stations_at_channel_level(self.settings)                  
                else :
                    self.trigger_error("Please select an event to proceed to the next step.")
                    return False         
                               
        st.session_state["show_error"] = False
        return True
    
    def render_stage_1(self):
        
        c1, c2, c3 = st.columns([1, 1, 1])
        title = "Events" if self.settings.selected_workflow == WorkflowType.EVENT_BASED else "Stations"

        with c1:
            if st.button("Previous"):
                self.previous_stage()

        with c2:
            st.write(f"### Step 1: Search & Select {title}")

        with c3:
            if st.button("Next"):
                if self.validate_and_adjust_selection(self.settings.selected_workflow):
                    self.next_stage()

            if st.session_state.get("show_error", False):
                if self.settings.selected_workflow == WorkflowType.EVENT_BASED:
                    selected_catalogs = self.event_components.settings.event.selected_catalogs
                    if selected_catalogs is None or len(selected_catalogs) <= 0:
                        st.error(st.session_state["error_message"])

                elif self.settings.selected_workflow in [WorkflowType.STATION_BASED, WorkflowType.CONTINUOUS]:
                    selected_invs = self.station_components.settings.station.selected_invs
                    if selected_invs is None or len(selected_invs) <= 0:
                        st.error(st.session_state["error_message"])                           

        # Render components based on selected workflow
        if self.settings.selected_workflow == WorkflowType.EVENT_BASED:
            self.event_components.render()
        else:
            self.station_components.render()

    def render_stage_2(self):

        c1, c2, c3 = st.columns([1, 1, 1])

        if self.settings.selected_workflow == WorkflowType.CONTINUOUS:
            self.settings = get_selected_stations_at_channel_level(self.settings)
            with c2:
                st.write("### Step 2: Get Waveforms")
                
            with c1:
                if st.button("Previous"):
                    selected_idx = self.station_components.get_selected_idx()
                    self.station_components.refresh_map(selected_idx=selected_idx,clear_draw=True)
                    self.previous_stage() 
            self.waveform_components.render()
        else:    

            title = "Stations" if self.settings.selected_workflow == WorkflowType.EVENT_BASED else "Events"
            with c1:
                if st.button("Previous"):
                    if self.settings.selected_workflow == WorkflowType.EVENT_BASED:
                        selected_idx = self.event_components.get_selected_idx()
                        self.event_components.refresh_map(selected_idx=selected_idx, clear_draw=True)
                    elif self.settings.selected_workflow == WorkflowType.STATION_BASED:
                        selected_idx = self.station_components.get_selected_idx()
                        self.station_components.refresh_map(selected_idx=selected_idx, clear_draw=True)

                    self.previous_stage()

            with c2:
                st.write(f"### Step 2: Search & Select {title}")                

            with c3:
                if st.button("Next"):
                    if self.validate_and_adjust_selection(self.settings.selected_workflow):
                        self.next_stage()
                    
                if st.session_state.get("show_error", False):
                    if self.settings.selected_workflow == WorkflowType.EVENT_BASED:
                        selected_invs = self.station_components.settings.station.selected_invs
                        if selected_invs is None or len(selected_invs) <= 0:
                            st.error(st.session_state["error_message"])
                    elif self.settings.selected_workflow == WorkflowType.STATION_BASED:
                        selected_catalogs = self.event_components.settings.event.selected_catalogs
                        if selected_catalogs is None or len(selected_catalogs) <= 0:
                            st.error(st.session_state["error_message"])

        if self.settings.selected_workflow == WorkflowType.EVENT_BASED:
            self.station_components.render()
        elif self.settings.selected_workflow == WorkflowType.STATION_BASED:
            self.event_components.render()
                   
    def render_stage_3(self):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            st.write("### Step 3: Waveforms")
        if self.settings.selected_workflow == WorkflowType.EVENT_BASED: 
            with c1:
                if st.button("Previous"):
                    selected_idx = self.station_components.get_selected_idx()
                    self.station_components.refresh_map(selected_idx=selected_idx,clear_draw=True)
                    self.previous_stage()


        if self.settings.selected_workflow == WorkflowType.STATION_BASED:
            with c1:
                if st.button("Previous"):
                    selected_idx = self.event_components.get_selected_idx()
                    self.event_components.refresh_map(selected_idx=selected_idx,clear_draw=True)
                    self.previous_stage()

        self.waveform_components.render()



    def render(self):
        if self.stage == 0:
            self.render_stage_0()

        if self.stage == 1:
            self.render_stage_1()

        if self.stage == 2:
            self.render_stage_2()

        if self.stage == 3:
            self.render_stage_3()
            
