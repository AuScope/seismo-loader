import streamlit as st
st.set_page_config(layout="wide")

from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.workflows import StationBasedWorkflow

init_settings()

if "station_based_workflow" not in st.session_state:
    station_based_workflow                  = StationBasedWorkflow(st.session_state.station_page)
    st.session_state.station_based_workflow = station_based_workflow
else:
    station_based_workflow                  = st.session_state.station_based_workflow

station_based_workflow.render()

