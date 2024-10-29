import streamlit as st

from seed_vault.ui.pages.helpers.common import init_settings
from seed_vault.ui.components.workflows import StationBasedWorkflow

init_settings()
st.set_page_config(layout="wide")

if "station_based_workflow" not in st.session_state:
    station_based_workflow                  = StationBasedWorkflow(st.session_state.station_page)
    st.session_state.station_based_workflow = station_based_workflow
else:
    station_based_workflow                  = st.session_state.station_based_workflow

station_based_workflow.render()

