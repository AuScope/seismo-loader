import streamlit as st
from seed_vault.ui.pages.helpers.common import init_settings

init_settings()


st.set_page_config(
    page_title="Seismo Loader",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("# Settings")


st.write("Use this page to put app settings such as folder paths.")
# sds_path = st.text_input("SDS Path", "./data/SDS")
# db_path = st.text_input("Database Path", "./data/database.sql")


st.write("""By the way, should we let user to change above paths at all? 
         I guess it would be better it would be a fix location as changing the paths
         might interrupt synchronisation.""")