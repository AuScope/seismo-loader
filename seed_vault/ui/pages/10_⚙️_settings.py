import streamlit as st
import pandas as pd
import time
from seed_vault.utils.clients import save_original_client

st.set_page_config(
    page_title="Settings",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

save_original_client()

from seed_vault.ui.pages.helpers.common import get_app_settings
from seed_vault.ui.components.settings import SettingsComponent

settings = get_app_settings()


if "settings_page" not in st.session_state:
    settings_page                  = SettingsComponent(settings)
    st.session_state.settings_page = settings_page
else:
    settings_page                  = st.session_state.settings_page
    

settings_page.render()