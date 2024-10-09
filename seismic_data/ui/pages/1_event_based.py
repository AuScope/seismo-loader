import streamlit as st
import pandas as pd

from seismic_data.models.common import CircleArea

from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.workflows import EventBasedWorkflow

init_settings()
st.set_page_config(layout="wide")


def main():

    if "event_based_workflow" not in st.session_state:
        event_based_workflow                  = EventBasedWorkflow(st.session_state.event_page)
        st.session_state.event_based_workflow = event_based_workflow
    else:
        event_based_workflow                  = st.session_state.event_based_workflow
    
    event_based_workflow.render()

if __name__ == "__main__":
    main()
