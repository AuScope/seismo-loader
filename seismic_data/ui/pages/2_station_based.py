import streamlit as st
from seismic_data.ui.pages.helpers.common import init_settings

init_settings()


st.set_page_config(
    page_title="Data Select",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("# Stations 🎈")
st.sidebar.markdown("# Placeholder")

st.write("Under construction.")