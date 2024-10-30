import streamlit as st
import pandas as pd
import time

from seed_vault.models.config import AuthConfig, SeismoLoaderSettings
from seed_vault.ui.pages.helpers.common import get_app_settings, set_app_settings, save_filter

from seed_vault.service.seismoloader import populate_database_from_sds



st.set_page_config(
    page_title="Seismo Loader",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = get_app_settings()


def render_auth():
    global settings
    def add_credential():
        for item in settings.auths:
            if item.nslc_code == "new":
                st.toast("You cannot define duplicate n.s.l.c code.")
                time.sleep(1)
                return
        settings.auths.append(AuthConfig(nslc_code="new", username="new", password="new"))
        save_filter(settings)
    
    with st.expander("Manage Credentials", expanded=True):
        st.write("## Auth Records")
        # auths_lst = [item.model_dump() for item in settings.auths]
        # edited_df = st.data_editor(pd.DataFrame(auths_lst), num_rows="dynamic")

        for index, auth in enumerate(settings.auths):
            c1,c2,c3,c4 = st.columns([1,1,1,3])
            # st.write(f"### Credential Set {index + 1}")

            with c1:
                nslc_code = st.text_input(f"n.s.l.c code", help="NSLC Code for (Network.Station.Location.Channel)", value=auth.nslc_code, key=f"nslc_{index}")
            with c2:
                username = st.text_input(f"Username", value=auth.username, key=f"username_{index}")
            with c3:
                password = st.text_input(f"Password", value=auth.password, type="password", key=f"password_{index}")

            # Update session state with edited values
            settings.auths[index] = AuthConfig(nslc_code=nslc_code, username=username, password=password)

            with c4:
                st.text("")
                st.text("")
                if st.button(f"Delete", key=f"remove_{index}"):
                    try:
                        settings.auths.pop(index)
                        save_filter(settings)
                        st.rerun()
                    except Exception as e:
                        st.error(f"An error occured: {str(e)}")

        if st.button("Add Credential Set"):
            try:
                add_credential()
                st.rerun()
            except Exception as e:
                st.error(f"An error occured: {str(e)}")


def render_db():
    global settings

    with st.expander("Manage Data", expanded=True):
        c1, c2 = st.columns([1,1])
        with c1:
            settings.db_path = st.text_input("Database Path", value=settings.db_path, help="Do not change this path, unless necessary!")
            settings.sds_path = st.text_input("Local Seismic Data Storage Path", value=settings.sds_path, help="Do not change this path, unless necessary!")

        st.write("## Sync database with SDS files")
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            search_patterns = st.text_input("Search Patterns", value="??.*.*.???.?.????.???", help="To input multiple values, separate your entries with comma.").strip().split(",")
        with c3:
            c11, c22 = st.columns([1,1])
            with c11:
                selected_date_type = st.selectbox("Date selection", ["All", "Custom Time"], index=0)
            with c22:
                if selected_date_type == "All":
                    newer_than=None
                else:
                    newer_than = st.date_input("Update Since")
        with c2:
            num_processes = st.number_input("Number of Processors", value=0, min_value=0)

        if st.button("Sync Database", help="Synchronizes the archive database with the available local seismic data based on the above parameters."):
            populate_database_from_sds(
                sds_path=settings.sds_path,
                db_path=settings.db_path,
                search_patterns=search_patterns,
                newer_than=newer_than,
                num_processes=num_processes,
            )

def render():
    global settings
    
    st.write("# Settings")

    render_db()
    render_auth()

    if st.button("Save Config"):
        try:
            # auths_lst_updated = [AuthConfig(**item) for item in edited_df.to_dict(orient='records')]
            # settings.auths = auths_lst_updated
            save_filter(settings)
            st.success("Successfully saved.")
        except Exception as e:
            st.error(f"An error occured. Make sure there is no null value in the table.")


render()