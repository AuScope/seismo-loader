import streamlit as st

st.set_page_config(
    page_title="Seed Vault",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
        section[data-testid="stSidebar"] {
            width: 800px; # Set the width to your desired value
        }
        section[data-testid="stMain"] {
            width: 100% !important; # Set the width to your desired value
            padding: 0;
        }
        # div[data-testid="stHorizontalBlock"] {
        #     display: flex;
        #     align-items: end;
        # }
        .vertical-align-bottom {
            display: flex;
            align-items: flex-end !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.workflows_combined import CombinedBasedWorkflow


if "combined_based_workflow" not in st.session_state:
    combined_based_workflow                  = CombinedBasedWorkflow()
    st.session_state.combined_based_workflow = combined_based_workflow
else:
    combined_based_workflow                  = st.session_state.combined_based_workflow

combined_based_workflow.render()



