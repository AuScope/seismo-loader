import streamlit as st

st.set_page_config(layout="wide")

from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.workflows import EventBasedWorkflow

init_settings()


if "event_based_workflow" not in st.session_state:
    event_based_workflow                  = EventBasedWorkflow(st.session_state.event_page)
    st.session_state.event_based_workflow = event_based_workflow
else:
    event_based_workflow                  = st.session_state.event_based_workflow

event_based_workflow.render()

