import streamlit as st

from seed_vault.ui.pages.helpers.common import get_app_settings
from seed_vault.ui.components.workflows import EventBasedWorkflow

get_app_settings()
st.set_page_config(layout="wide")


if "event_based_workflow" not in st.session_state:
    event_based_workflow                  = EventBasedWorkflow(st.session_state.event_page)
    st.session_state.event_based_workflow = event_based_workflow
else:
    event_based_workflow                  = st.session_state.event_based_workflow

event_based_workflow.render()

