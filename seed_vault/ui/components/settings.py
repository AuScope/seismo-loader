import streamlit as st
import pandas as pd
import time

from seed_vault.models.config import AuthConfig, SeismoLoaderSettings
from seed_vault.ui.pages.helpers.common import save_filter

from seed_vault.service.seismoloader import populate_database_from_sds
from seed_vault.utils.clients import load_original_client, load_extra_client, save_extra_client




class SettingsComponent:
    settings: SeismoLoaderSettings
    is_new_cred_added = None
    df_clients = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings  = settings

    
    def add_credential(self):
        for item in self.settings.auths:
            if item.nslc_code == "new":
                return False
        self.settings.auths.append(AuthConfig(nslc_code="new", username="new", password="new"))
        save_filter(self.settings)
        return True
    
    
    def reset_is_new_cred_added(self):
        # time.sleep(5)
        self.is_new_cred_added = None
        # st.rerun()

    
    def render_auth(self):
        st.write("## Auth Records")
        # auths_lst = [item.model_dump() for item in settings.auths]
        # edited_df = st.data_editor(pd.DataFrame(auths_lst), num_rows="dynamic")

        for index, auth in enumerate(self.settings.auths):
            c1,c2,c3,c4 = st.columns([1,1,1,3])
            # st.write(f"### Credential Set {index + 1}")

            with c1:
                nslc_code = st.text_input(f"N.S.L.C. code", help="NSLC Code for (Network.Station.Location.Channel)", value=auth.nslc_code, key=f"nslc_{index}")
            with c2:
                username = st.text_input(f"Username", value=auth.username, key=f"username_{index}")
            with c3:
                password = st.text_input(f"Password", value=auth.password, type="password", key=f"password_{index}")

            # Update session state with edited values
            self.settings.auths[index] = AuthConfig(nslc_code=nslc_code, username=username, password=password)

            with c4:
                st.text("")
                st.text("")
                if st.button(f"Delete", key=f"remove_{index}"):
                    try:
                        self.settings.auths.pop(index)
                        save_filter(self.settings)
                        self.reset_is_new_cred_added()
                        st.rerun()
                    except Exception as e:
                        st.error(f"An error occured: {str(e)}")

        if st.button("Add Credential Set"):
            try:
                self.reset_is_new_cred_added()
                self.is_new_cred_added = self.add_credential()
                st.rerun()
            except Exception as e:
                st.error(f"An error occured: {str(e)}")

        if self.is_new_cred_added is not None:
            if self.is_new_cred_added:
                st.success("Added a new auth. Please fill up the entries.")
            else:
                st.error("You cannot define duplicate N.S.L.C code.")

            # self.reset_is_new_cred_added()

        
    def render_db(self):
        c1, c2 = st.columns([1,1])
        with c1:
            self.settings.db_path = st.text_input("Database Path", value=self.settings.db_path, help="Do not change this path, unless necessary!")
            self.settings.sds_path = st.text_input("Local Seismic Data Archive Path in [SDS structure](https://www.seiscomp.de/seiscomp3/doc/applications/slarchive/SDS.html)",
                                                   value=self.settings.sds_path, help="Do not change this path, unless necessary!")

        st.write("## Sync database with existing archive")
        c1, c2, c3, c4 = st.columns([1,1,1,2])
        with c1:
            search_patterns = st.text_input("Search Patterns", value="??.*.*.???.?.????.???", help="To input multiple values, separate your entries with comma.").strip().split(",")
        with c4:
            c11, c22 = st.columns([1,1])
            with c11:
                selected_date_type = st.selectbox("Date selection", ["All", "Custom Time"], index=0)
            with c22:
                if selected_date_type == "All":
                    newer_than=None
                else:
                    newer_than = st.date_input("Update Since")
        with c2:
            curr_val = int(self.settings.proccess.num_processes)
            self.settings.proccess.num_processes = st.text_input("Number of Processors", value=curr_val, help="Number of Processors >= 0. If set to zero, the app will use all available cpu to perform the operation.")

        with c3:
            curr_val = int(self.settings.proccess.gap_tolerance)
            self.settings.proccess.gap_tolerance = st.text_input("Gap Tolerance (s)", value=curr_val)

        if st.button("Sync Database", help="Synchronizes your SDS archive given the above parameters."):
            self.reset_is_new_cred_added()
            save_filter(self.settings)
            populate_database_from_sds(
                sds_path=self.settings.sds_path,
                db_path=self.settings.db_path,
                search_patterns=search_patterns,
                newer_than=newer_than,
                num_processes=self.settings.proccess.num_processes,
                gap_tolerance=self.settings.proccess.gap_tolerance
            )


    def render_clients(self):
        c1, c2 = st.columns([1,1])
        extra_clients = load_extra_client()
        orig_clients  = load_original_client()
        with c1:
            st.write("## Extra Clients")
            df = pd.DataFrame([{"Client Name": k, "Url": v} for k,v in extra_clients.items()])
            if df.empty:
                df = pd.DataFrame(columns=["Client Name", "Url"])
            self.df_clients = st.data_editor(df, hide_index = True, num_rows = "dynamic")            
            # st.write(extra_clients)
        with c2:
            st.write("## Existing Clients (via ObsPy)")
            st.write(orig_clients)


    def render(self):
        c1, c2, c3 = st.columns([1,1, 2])
        with c1:
            st.write("# Settings")
        with c2:
            st.text("")
            st.text("")
            if st.button("Save Config"):
                try:
                    self.reset_is_new_cred_added()
                    save_filter(self.settings)
                    extra_clients = {item["Client Name"]: item["Url"] for item in self.df_clients.to_dict(orient='records')}
                    save_extra_client(extra_clients)
                    with c3:
                        st.text("")
                        st.success("Config is successfully saved.")
                except Exception as e:
                    with c3:
                        st.text("")
                        st.error(f"An error occured. Make sure there is no null value in the table.")

        tab1, tab2, tab3 = st.tabs(["Data", "Credentials", "Clients"])
        with tab1:
            self.render_db()
        with tab2:
            self.render_auth()
        with tab3:
            self.render_clients()

        