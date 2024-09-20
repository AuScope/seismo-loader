import streamlit as st
from seismic_data.ui.pages.helpers.common import init_settings

init_settings()

st.set_page_config(
    page_title="Seismo Loader",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("# Main page 🎈")
st.sidebar.markdown("# Placeholder")

st.write("Navigate to other pages.")