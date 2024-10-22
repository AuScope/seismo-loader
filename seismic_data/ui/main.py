import streamlit as st
from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.workflows_combined import CombinedBasedWorkflow

# init_settings()
# st.set_page_config(layout="wide")

st.set_page_config(
    page_title="Seed Vault",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)


if "combined_based_workflow" not in st.session_state:
    combined_based_workflow                  = CombinedBasedWorkflow()
    st.session_state.combined_based_workflow = combined_based_workflow
else:
    combined_based_workflow                  = st.session_state.combined_based_workflow

combined_based_workflow.render()



