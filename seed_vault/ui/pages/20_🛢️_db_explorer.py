import streamlit as st
import pandas as pd
import time
from seed_vault.utils.clients import save_original_client

st.set_page_config(
    page_title="Data Explorer",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

save_original_client()

from seed_vault.ui.pages.helpers.common import get_app_settings
from seed_vault.ui.components.data_explorer import DataExplorerComponent

settings = get_app_settings()


if "data_explorer_page" not in st.session_state:
    data_explorer_page                  = DataExplorerComponent(settings)
    st.session_state.data_explorer_page = data_explorer_page
else:
    data_explorer_page                  = st.session_state.data_explorer_page
    

data_explorer_page.render()