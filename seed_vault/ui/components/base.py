from typing import List, Any, Optional, Union
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta,date
import uuid
from obspy.core.event import Catalog, read_events
from obspy.core.inventory import Inventory, read_inventory
from io import BytesIO



from seed_vault.ui.components.card import create_card
from seed_vault.ui.components.map import create_map, add_area_overlays, add_data_points, clear_map_layers, clear_map_draw,add_map_draw
from seed_vault.ui.pages.helpers.common import get_selected_areas, save_filter

from seed_vault.service.events import get_event_data, event_response_to_df
from seed_vault.service.stations import get_station_data, station_response_to_df
from seed_vault.service.seismoloader import convert_radius_to_degrees, convert_degrees_to_radius_meter

from seed_vault.models.config import SeismoLoaderSettings, GeometryConstraint, EventConfig, StationConfig
from seed_vault.models.common import CircleArea, RectangleArea

from seed_vault.enums.config import GeoConstraintType, Levels
from seed_vault.enums.ui import Steps

from seed_vault.service.utils import convert_to_date
import io
import os


class BaseComponentTexts:
    CLEAR_ALL_MAP_DATA = "Clear All"
    DOWNLOAD_CONFIG = "Download Config"
    SAVE_CONFIG = "Save Config"
    CONFIG_TEMPLATE_FILE="config_template.cfg"
    CONFIG_EVENT_FILE="config_event"
    CONFIG_STATION_FILE="config_station"

    def __init__(self, config_type: Steps):
        if config_type == Steps.EVENT:
            self.STEP   = "event"
            self.PREV_STEP = "station"

            self.GET_DATA_TITLE = "Select Data Tools"
            self.BTN_GET_DATA = "Get Events"
            self.SELECT_DATA_TITLE = "Select Events from Map or Table"
            self.SELECT_MARKER_TITLE = "#### Select Events from map"
            self.SELECT_MARKER_MSG   = "Select an event from map and Add to Selection."
            self.SELECT_DATA_TABLE_TITLE = "Select Events from table"
            self.SELECT_DATA_TABLE_MSG = "Tick events from the table to view your selected events on the map."

            self.PREV_SELECT_NO  = "Total Number of Selected Events"
            self.SELECT_AREA_AROUND_MSG = "Define an area around the selected events."

        if config_type == Steps.STATION:
            self.STEP   = "station"
            self.PREV_STEP = "event"

            self.GET_DATA_TITLE = "Select Data Tools"
            self.BTN_GET_DATA = "Get Stations"
            self.SELECT_DATA_TITLE = "Select Stations from Map or Table"
            self.SELECT_MARKER_TITLE = "#### Select Stations from map"
            self.SELECT_MARKER_MSG   = "Select an station from map and Add to Selection."
            self.SELECT_DATA_TABLE_TITLE = "Select Stations from table"
            self.SELECT_DATA_TABLE_MSG = "Tick stations from the table to view your selected stations on the map."

            self.PREV_SELECT_NO  = "Total Number of Selected Stations"
            self.SELECT_AREA_AROUND_MSG = "Define an area around the selected stations."


class BaseComponent:
    settings: SeismoLoaderSettings
    step_type: Steps
    prev_step_type: Steps

    TXT: BaseComponentTexts
    stage: int

    all_current_drawings: List[GeometryConstraint] = []
    all_feature_drawings: List[GeometryConstraint] = []
    df_markers          : pd  .DataFrame           = pd.DataFrame()
    df_data_edit        : pd  .DataFrame           = pd.DataFrame()
    catalogs            : Catalog = Catalog(events=None)
    inventories         : Inventory = Inventory()
    
    map_disp                    = None
    map_fg_area                 = None
    map_fg_marker               = None
    map_fg_prev_selected_marker = None
    map_height                  = 500
    map_output                  = None
    marker_info                 = None
    clicked_marker_info         = None
    warning                     = None
    error                       = None
    df_rect                     = None
    df_circ                     = None
    col_color                   = None  
    col_size                    = None
    fig_color_bar               = None
    df_markers_prev             = pd.DataFrame()

    cols_to_exclude             = ['detail', 'is_selected']

    @property
    def page_type(self) -> str:
        if self.prev_step_type is not None and self.prev_step_type != Steps.NONE:
            return self.prev_step_type
        else:
            return self.step_type

    def __init__(self, settings: SeismoLoaderSettings, step_type: Steps, prev_step_type: Steps, stage: int):
        self.settings       = settings
        self.step_type      = step_type
        self.prev_step_type = prev_step_type
        self.stage          = stage
        self.map_id         = f"map_{step_type.value}_{prev_step_type.value}_{stage}" if prev_step_type else f"map_{step_type.value}_no_prev_{stage}"   # str(uuid.uuid4())
        self.map_disp       = create_map(map_id=self.map_id)
        self.TXT            = BaseComponentTexts(step_type)

        self.all_feature_drawings = self.get_geo_constraint()
        self.map_fg_area= add_area_overlays(areas=self.get_geo_constraint()) 
        if self.catalogs:
            self.df_markers = event_response_to_df(self.catalogs)

        if self.step_type == Steps.EVENT:
            self.col_color = "depth (km)"
            self.col_size  = "magnitude"
            self.config = self.settings.event
        if self.step_type == Steps.STATION:
            self.col_color = "network"
            self.col_size  = None
            self.config =  self.settings.station

    def get_key_element(self, name):        
        return f"{name}-{self.step_type.value}-{self.stage}"


    def get_geo_constraint(self):
        if self.step_type == Steps.EVENT:
            return self.settings.event.geo_constraint
        if self.step_type == Steps.STATION:
            return self.settings.station.geo_constraint
        return []
    
    def set_geo_constraint(self, geo_constraint: List[GeometryConstraint]):
        if self.step_type == Steps.EVENT:
            self.settings.event.geo_constraint = geo_constraint
        if self.step_type == Steps.STATION:
            self.settings.station.geo_constraint = geo_constraint


    # ====================
    # FILTERS
    # ====================
    def import_export(self):
        def reset_import_setting_processed():
            if uploaded_file is not None:
                uploaded_file_info = f"{uploaded_file.name}-{uploaded_file.size}"               
                if "uploaded_file_info" not in st.session_state or st.session_state.uploaded_file_info != uploaded_file_info:
                    st.session_state['import_setting_processed'] = False
                    st.session_state['uploaded_file_info'] = uploaded_file_info  


        # st.sidebar.markdown("### Import/Export Settings")
        
        with st.expander("Import & Export", expanded=False):
            tab1, tab2 = st.tabs(["Settings", f"{self.TXT.STEP.title()}s"])
            with tab1:
                config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../service/config.cfg')
                config_file_path = os.path.abspath(config_file_path)
                
                st.markdown("#### ⬇️ Export Settings")

                if os.path.exists(config_file_path):
                    with open(config_file_path, "r") as file:
                        file_data = file.read()

                    st.download_button(
                        label="Download file",
                        data=file_data,  
                        file_name="config.cfg",  
                        mime="application/octet-stream",  
                        help="Download the current settings.",
                        use_container_width=True,
                    )
                else:
                    st.caption("No config file available for download.")

                st.markdown("#### 📂 Import Settings")
                uploaded_file = st.file_uploader(
                    "Import Settings",type=["cfg"], on_change=reset_import_setting_processed,
                    help="Upload a config file (.cfg) to update settings." , label_visibility="collapsed"
                )

                if uploaded_file:
                    if not st.session_state.get('import_setting_processed', False):
                        file_like_object = io.BytesIO(uploaded_file.getvalue())
                        text_file_object = io.TextIOWrapper(file_like_object, encoding='utf-8')

                        self.clear_all_data()
                        self.settings = SeismoLoaderSettings.from_cfg_file(text_file_object)
                        self.settings.load_url_mapping()

                        self.settings.event.geo_constraint = []
                        self.settings.station.geo_constraint = []
                        self.refresh_map(reset_areas=True, clear_draw=True)

                        st.session_state['import_setting_processed'] = True                    
                        st.success("Settings imported successfully!")   
            with tab2:
                c2_export = self.render_export_import()

            return c2_export

    def event_filter(self):
        start_time = convert_to_date(self.settings.event.date_config.start_time)
        end_time = convert_to_date(self.settings.event.date_config.end_time)

        if 'initial_event_settings' not in st.session_state:
            st.session_state['initial_event_settings'] = self.settings.event.dict()

        with st.sidebar:
            self.render_map_right_menu()
            with st.expander("### Filters", expanded=True):
                client_options = list(self.settings.client_url_mapping.keys())
                try:
                    self.settings.event.client = st.selectbox(
                        'Choose a client:', client_options, 
                        index=client_options.index(self.settings.event.client), 
                        key="event-pg-client-event"
                    )
                except ValueError as e:
                    st.error(f"Error: {str(e)}. Event client is set to {self.settings.event.client}, which seems does not exists. Please navigate to the settings page and use the Clients tab to add the client or fix the stored config.cfg file.")

                c1, c2 = st.columns([1,1])

                with c1:
                    self.settings.event.date_config.start_time = st.date_input("Start Date", start_time, key="event-pg-start-date-event")
                with c2:
                    self.settings.event.date_config.end_time = st.date_input("End Date", end_time, key="event-pg-end-date-event")

                if self.settings.event.date_config.start_time > self.settings.event.date_config.end_time:
                    st.error("Error: End Date must fall after Start Date.")

                self.settings.event.min_magnitude, self.settings.event.max_magnitude = st.slider(
                    "Min Magnitude", 
                    min_value=-2.0, max_value=10.0, 
                    value=(self.settings.event.min_magnitude, self.settings.event.max_magnitude), 
                    step=0.1, key="event-pg-mag"
                )

                self.settings.event.min_depth, self.settings.event.max_depth = st.slider(
                    "Min Depth (km)", 
                    min_value=-5.0, max_value=800.0, 
                    value=(self.settings.event.min_depth, self.settings.event.max_depth), 
                    step=1.0, key="event-pg-depth"
                )

                if st.button(f"Update {self.TXT.STEP.title()}s", key=self.get_key_element(f"Update {self.TXT.STEP}s")):
                    self.refresh_map(reset_areas=False, clear_draw=False, rerun=False)
                
            c2_export = self.import_export()

        new_event_settings = self.settings.event.dict() 
        if new_event_settings != st.session_state['initial_event_settings']:
            save_filter(self.settings)
            # self.refresh_map()
            st.session_state['initial_event_settings'] = new_event_settings 
        
        save_filter(self.settings)

        return c2_export


    def station_filter(self):
        start_time = convert_to_date(self.settings.station.date_config.start_time)
        end_time = convert_to_date(self.settings.station.date_config.end_time)

        with st.sidebar:
            self.render_map_right_menu()
                
            with st.expander("### Filters", expanded=True):
                client_options = list(self.settings.client_url_mapping.keys())
                try:
                    self.settings.station.client = st.selectbox(
                        'Choose a client:', client_options, 
                        index=client_options.index(self.settings.station.client), 
                        key="event-pg-client-station"
                    )
                except ValueError as e:
                    st.error(f"Error: {str(e)}. Station client is set to {self.settings.station.client}, which seems does not exists. Please navigate to the settings page and use the Clients tab to add the client or fix the stored config.cfg file.")

                c11, c12 = st.columns([1,1])
                with c11:
                    self.settings.station.date_config.start_time = st.date_input("Start Date", start_time, key="event-pg-start-date-station")
                with c12:
                    self.settings.station.date_config.end_time = st.date_input("End Date", end_time, key="event-pg-end-date-station")

                if self.settings.station.date_config.start_time > self.settings.station.date_config.end_time:
                    st.error("Error: End Date must fall after Start Date.")

                c21, c22 = st.columns([1,1])
                c31, c32 = st.columns([1,1])

                with c21:
                    self.settings.station.network = st.text_input("Network",   self.settings.station.network, key="event-pg-net-txt-station")
                with c22:
                    self.settings.station.station = st.text_input("Station",   self.settings.station.station, key="event-pg-sta-txt-station")
                with c31:
                    self.settings.station.location = st.text_input("Location", self.settings.station.location, key="event-pg-loc-txt-station")
                with c32:
                    self.settings.station.channel = st.text_input("Channel",   self.settings.station.channel, key="event-pg-cha-txt-station")

                self.settings.station.include_restricted = st.checkbox(
                    "Include Restricted Data", 
                    value=False,  # Default to unchecked
                    key="event-pg-include-restricted-station"
                )

                self.settings.station.level = Levels.CHANNEL

                if st.button(f"Update {self.TXT.STEP.title()}s", key=self.get_key_element(f"Update {self.TXT.STEP}s")):
                    self.refresh_map(reset_areas=False, clear_draw=False, rerun=False)

            c2_export = self.import_export()

        save_filter(self.settings)

        return c2_export

    # ====================
    # MAP
    # ====================
    def update_filter_geometry(self, df, geo_type: GeoConstraintType, geo_constraint: List[GeometryConstraint]):
        add_geo = []
        for _, row in df.iterrows():
            coords = row.to_dict()
            if geo_type == GeoConstraintType.BOUNDING:
                add_geo.append(GeometryConstraint(coords=RectangleArea(**coords)))
            if geo_type == GeoConstraintType.CIRCLE:
                add_geo.append(GeometryConstraint(coords=CircleArea(**coords)))

        new_geo = [
            area for area in geo_constraint
            if area.geo_type != geo_type
        ]
        new_geo.extend(add_geo)

        self.set_geo_constraint(new_geo)

    def update_circle_areas(self):
        geo_constraint = self.get_geo_constraint()
        lst_circ = [area.coords.model_dump() for area in geo_constraint
                    if area.geo_type == GeoConstraintType.CIRCLE ]

        if lst_circ:
            st.write(f"Circle Areas (Degree)")
            original_df_circ = pd.DataFrame(lst_circ, columns=CircleArea.model_fields)
            self.df_circ = st.data_editor(original_df_circ, key=f"circ_area", hide_index=True)

            circ_changed = not original_df_circ.equals(self.df_circ)

            if circ_changed:
                self.update_filter_geometry(self.df_circ, GeoConstraintType.CIRCLE, geo_constraint)
                self.refresh_map(reset_areas=False, clear_draw=True)

    def update_rectangle_areas(self):
        geo_constraint = self.get_geo_constraint()
        lst_rect = [area.coords.model_dump() for area in geo_constraint
                    if isinstance(area.coords, RectangleArea) ]

        if lst_rect:
            st.write(f"Rectangle Areas")
            original_df_rect = pd.DataFrame(lst_rect, columns=RectangleArea.model_fields)
            self.df_rect = st.data_editor(original_df_rect, key=f"rect_area", hide_index=True)

            rect_changed = not original_df_rect.equals(self.df_rect)

            if rect_changed:
                self.update_filter_geometry(self.df_rect, GeoConstraintType.BOUNDING, geo_constraint)
                self.refresh_map(reset_areas=False, clear_draw=True)


    def update_selected_data(self):

        if self.df_data_edit is None or self.df_data_edit.empty:
            if 'is_selected' not in self.df_markers.columns:
                self.df_markers['is_selected'] = False
            return
                                  
        if self.step_type == Steps.EVENT:
            self.settings.event.selected_catalogs = Catalog(events=None)
            for i, event in enumerate(self.catalogs):
                if self.df_markers.loc[i, 'is_selected']:
                    self.settings.event.selected_catalogs.append(event)
            return
        if self.step_type == Steps.STATION:
            self.settings.station.selected_invs = None
            is_init = False
            if not self.df_markers.empty and 'is_selected' in list(self.df_markers.columns):
                for idx, row in self.df_markers[self.df_markers['is_selected']].iterrows():
                    if not is_init:
                        self.settings.station.selected_invs = self.inventories.select(station=row["station"])
                        is_init = True
                    else:
                        self.settings.station.selected_invs += self.inventories.select(station=row["station"])
            return


    def handle_update_data_points(self, selected_idx):
        if not self.df_markers.empty:
            cols = self.df_markers.columns
            cols_to_disp = {c:c.capitalize() for c in cols if c not in self.cols_to_exclude}
            self.map_fg_marker, self.marker_info, self.fig_color_bar = add_data_points( self.df_markers, cols_to_disp, step=self.step_type, selected_idx = selected_idx, col_color=self.col_color, col_size=self.col_size)
        else:
            self.warning = "No data found."


    def get_data_globally(self):
        self.clear_all_data()
        clear_map_draw(self.map_disp)
        self.handle_get_data()
        st.rerun()


    def refresh_map(self, reset_areas = False, selected_idx = None, clear_draw = False, rerun = False, get_data = True, recreate_map = False):
        geo_constraint = self.get_geo_constraint()

        if recreate_map:
            self.map_disp = create_map(map_id=self.map_id)
        
        if clear_draw:
            clear_map_draw(self.map_disp)
            self.all_feature_drawings = geo_constraint
            self.map_fg_area= add_area_overlays(areas=geo_constraint)
        else:
            if reset_areas:
                geo_constraint = []
            else:
                geo_constraint = self.all_current_drawings + self.all_feature_drawings

        self.set_geo_constraint(geo_constraint)

        if selected_idx != None:
            self.handle_update_data_points(selected_idx)
        else:
            # @NOTE: Below is added to resolve triangle marker displays.
            #        But it results in map blinking and hence a chance to
            #        break the map.
            if not clear_draw:
                clear_map_draw(self.map_disp)
                self.all_feature_drawings = geo_constraint
                self.map_fg_area= add_area_overlays(areas=geo_constraint)
            if get_data:
                self.handle_get_data()
        
        # elif len(geo_constraint) > 0:
        #     self.handle_get_data()

        if rerun:
            st.rerun()
    
    def reset_markers(self):
        self.map_fg_marker = None
        self.df_markers    = pd.DataFrame()
    # ====================
    # GET DATA
    # ====================

    def handle_get_data(self, is_import: bool = False, uploaded_file = None):
        self.warning = None
        self.error   = None
        try:
            if self.step_type == Steps.EVENT:
                self.catalogs = Catalog()
                # self.catalogs = get_event_data(self.settings.model_dump_json())
                if is_import:
                    self.import_xml(uploaded_file)
                else:
                    self.catalogs = get_event_data(self.settings)

                if self.catalogs:
                    self.df_markers = event_response_to_df(self.catalogs)
                else:
                    self.reset_markers()

            if self.step_type == Steps.STATION:
                self.inventories = Inventory()
                # self.inventories = get_station_data(self.settings.model_dump_json())
                if is_import:
                    self.import_xml(uploaded_file)
                else:
                    self.inventories = get_station_data(self.settings)
                if self.inventories:
                    self.df_markers = station_response_to_df(self.inventories)
                else:
                    self.reset_markers()
                
            if not self.df_markers.empty:
                cols = self.df_markers.columns                
                cols_to_disp = {c:c.capitalize() for c in cols if c not in self.cols_to_exclude}
                self.map_fg_marker, self.marker_info, self.fig_color_bar = add_data_points( self.df_markers, cols_to_disp, step=self.step_type, col_color=self.col_color, col_size=self.col_size)

            else:
                self.warning = "No data available."

        except Exception as e:
            print(f"An unexpected error occurred: {str(e)}")
            self.error = f"Error: {str(e)}"


    def clear_all_data(self):
        self.map_fg_marker= None
        self.map_fg_area= None
        self.df_markers = pd.DataFrame()
        self.all_current_drawings = []
        
        if self.step_type == Steps.EVENT:
            self.catalogs=Catalog()
            self.settings.event.geo_constraint = []
        if self.step_type == Steps.STATION:
            self.inventories = Inventory()
            self.settings.station.geo_constraint = []

        self.update_rectangle_areas()
        self.update_circle_areas()


    def get_selected_marker_info(self):
        info = self.clicked_marker_info
        if self.step_type == Steps.EVENT:
            return f"Event No {info['id']}: {info['Magnitude']} {info['Magnitude type']}, {info['Depth (km)']} km, {info['Place']}"
        if self.step_type == Steps.STATION:
            return f"Station No {info['id']}: {info['Network']}, {info['Station']}"
    # ===================
    # SELECT DATA
    # ===================
    def get_selected_idx(self):
        if self.df_markers.empty:
            return []
        
        mask = self.df_markers['is_selected']
        return self.df_markers[mask].index.tolist()

    def sync_df_markers_with_df_edit(self):
        if self.df_data_edit is None:
            # st.error("No data has been edited yet. Please make a selection first.")
            return

        if 'is_selected' not in self.df_data_edit.columns:
            # st.error("'is_selected' column is missing from the edited data.")
            return

        self.df_markers['is_selected'] = self.df_data_edit['is_selected']
    
    def refresh_map_selection(self):
        selected_idx = self.get_selected_idx()
        self.update_selected_data()
        self.refresh_map(reset_areas=False, selected_idx=selected_idx, rerun=True)


    # ===================
    # PREV SELECTION
    # ===================
    def get_prev_step_df(self):
        if self.prev_step_type == Steps.EVENT:
            self.df_markers_prev = event_response_to_df(self.settings.event.selected_catalogs)
            return

        if self.prev_step_type == Steps.STATION:
            self.df_markers_prev = station_response_to_df(self.settings.station.selected_invs)
            return

        self.df_markers_prev = pd.DataFrame()

    def display_prev_step_selection_marker(self):
        if self.stage > 1:
            col_color = None
            col_size  = None
            if self.prev_step_type == Steps.EVENT:
                col_color = "depth (km)"
                col_size  = "magnitude"
            
            if self.prev_step_type == Steps.STATION:
                col_color = "network"

            if not self.df_markers_prev.empty:
                cols = self.df_markers_prev.columns
                cols_to_disp = {c:c.capitalize() for c in cols if c not in self.cols_to_exclude}
                selected_idx = self.df_markers_prev.index.tolist()
                self.map_fg_prev_selected_marker, _, _ = add_data_points( self.df_markers_prev, cols_to_disp, step=self.prev_step_type,selected_idx=selected_idx, col_color=col_color, col_size=col_size)

        
    def display_prev_step_selection_table(self):
        if self.stage > 1:
            if self.df_markers_prev.empty:
                st.write(f"No selected {self.TXT.PREV_STEP}s")
            else:
                # with st.expander(f"Search around {self.TXT.PREV_STEP}", expanded = True):
                self.area_around_prev_step_selections()
                # st.write(f"Total Number of Selected {self.TXT.PREV_STEP.title()}s: {len(self.df_markers_prev)}")
                # st.dataframe(self.df_markers_prev, use_container_width=True)

    
    def area_around_prev_step_selections(self):

        st.markdown(
            """
            <style>
            div.stButton > button {
                margin-top: 25px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.write(f"Define an area around the selected {self.TXT.STEP}s.")
        c1, c2 = st.columns([1, 1])

        with c1:
            min_radius_str = st.text_input("Minimum radius (degree)", value="0")
        with c2:
            max_radius_str = st.text_input("Maximum radius (degree)", value="15")

        try:
            min_radius = float(min_radius_str)
            max_radius = float(max_radius_str)
        except ValueError:
            st.error("Please enter valid numeric values for the radius.")
            return

        if min_radius >= max_radius:
            st.error("Maximum radius should be greater than minimum radius.")
            return

        if not hasattr(self, 'prev_min_radius') or not hasattr(self, 'prev_max_radius'):
            self.prev_min_radius = None
            self.prev_max_radius = None

        # with c3:
        if st.button("Draw Area", key=self.get_key_element("Draw Area")):
            if self.prev_min_radius is None or self.prev_max_radius is None or min_radius != self.prev_min_radius or max_radius != self.prev_max_radius:                
                self.update_area_around_prev_step_selections(min_radius, max_radius)
                self.prev_min_radius = min_radius
                self.prev_max_radius = max_radius

            self.refresh_map(reset_areas=False, clear_draw=True)
            st.rerun()

    def update_area_around_prev_step_selections(self, min_radius, max_radius):
        min_radius_value = float(min_radius) # * 1000
        max_radius_value = float(max_radius) # * 1000

        updated_constraints = []

        geo_constraints = self.get_geo_constraint()

        for geo in geo_constraints:
            if geo.geo_type == GeoConstraintType.CIRCLE:
                lat, lng = geo.coords.lat, geo.coords.lng
                matching_event = self.df_markers_prev[(self.df_markers_prev['latitude'] == lat) & (self.df_markers_prev['longitude'] == lng)]

                if not matching_event.empty:
                    geo.coords.min_radius = min_radius_value
                    geo.coords.max_radius = max_radius_value
            updated_constraints.append(geo)

        for _, row in self.df_markers_prev.iterrows():
            lat, lng = row['latitude'], row['longitude']
            if not any(
                geo.geo_type == GeoConstraintType.CIRCLE and geo.coords.lat == lat and geo.coords.lng == lng
                for geo in updated_constraints
            ):
                new_donut = CircleArea(lat=lat, lng=lng, min_radius=min_radius_value, max_radius=max_radius_value)
                geo = GeometryConstraint(geo_type=GeoConstraintType.CIRCLE, coords=new_donut)
                updated_constraints.append(geo)

        self.set_geo_constraint(updated_constraints)

    # ===================
    # FILES
    # ===================
    def export_xml_bytes(self, export_selected: bool = True):
        with BytesIO() as f:
            if not self.df_markers.empty and len(self.df_markers) > 0:
                if export_selected:
                # self.sync_df_markers_with_df_edit()
                    self.update_selected_data()
            
                if self.step_type == Steps.STATION:                
                    inv = self.settings.station.selected_invs if export_selected else self.inventories
                    if inv:
                        inv.write(f, format='STATIONXML')

                if self.step_type == Steps.EVENT:
                    cat = self.settings.event.selected_catalogs if export_selected else self.catalogs
                    if cat:
                        cat.write(f, format="QUAKEML")

            # if f.getbuffer().nbytes == 0:
            #     f.write(b"No Data")     

            return f.getvalue()
        

    def import_xml(self, uploaded_file):
        if uploaded_file is not None:
            if self.step_type == Steps.STATION:
                inv = read_inventory(uploaded_file)
                self.inventories = Inventory()
                self.inventories += inv
            if self.step_type == Steps.EVENT:
                cat = read_events(uploaded_file)
                self.catalogs = Catalog()
                self.catalogs.extend(cat)
                

    # ===================
    # WATCHER
    # ===================
    def watch_all_drawings(self, all_drawings):
        if self.all_current_drawings != all_drawings:
            self.all_current_drawings = all_drawings
            self.refresh_map(rerun=True, get_data=True)


    # ===================
    # RENDER
    # ===================
    def render_map_buttons(self):
        c1, c2 = st.columns([1,1])
        with c1:
            if st.button(f"Global {self.TXT.STEP.title()}s", key=self.get_key_element(f"Global {self.TXT.STEP}s")):
                self.clear_all_data()
                self.refresh_map(reset_areas=True, clear_draw=True, rerun=True, get_data=True)
        with c2:
            if st.button(self.TXT.CLEAR_ALL_MAP_DATA, key=self.get_key_element(self.TXT.CLEAR_ALL_MAP_DATA)):
                self.clear_all_data()
                self.refresh_map(reset_areas=True, clear_draw=True, rerun=True, get_data=False)

        if st.button("Reload", help="Reloads the map"):
            self.refresh_map(get_data=False, rerun=True, recreate_map=True)
        st.info("Use **Reload** button if the map is collapsed or some layers are missing.")
        st.info(f"Use **map tools** to search **{self.TXT.STEP}s** in confined areas.")

    def render_export_import(self):
        st.write(f"#### Export/Import {self.TXT.STEP.title()}s")

        c11, c22 = st.columns([1,1])
        with c11:
            # @NOTE: Download Selected had to be with the table.
            # if (len(self.catalogs.events) > 0 or len(self.inventories.get_contents().get('stations')) > 0):
            st.download_button(
                f"Download All", 
                key=self.get_key_element(f"Download All {self.TXT.STEP.title()}s"),
                data=self.export_xml_bytes(export_selected=False),
                file_name = f"{self.TXT.STEP}s.xml",
                mime="application/xml",
                disabled=(len(self.catalogs.events) == 0 and len(self.inventories.get_contents().get('stations')) == 0)
            )

        def reset_uploaded_file_processed():
            st.session_state['uploaded_file_processed'] = False

        uploaded_file = st.file_uploader(f"Import {self.TXT.STEP.title()}s from a File", type=["xml"], on_change=lambda:  reset_uploaded_file_processed())
        if uploaded_file and not st.session_state['uploaded_file_processed']:
            self.clear_all_data()
            self.refresh_map(reset_areas=True, clear_draw=True)
            self.handle_get_data(is_import=True, uploaded_file=uploaded_file)
            st.session_state['uploaded_file_processed'] = True

        return c22
        
    def render_actions_side_menu(self):        
        st.write("### Actions")
        # with st.expander(f"Actions", expanded = True):
        tab1, tab2 = st.tabs(["Map", "Export/Import"])
        with tab1:
            self.render_map_buttons()
        with tab2:
            c2_export = self.render_export_import()

        return c2_export

    def render_map_right_menu(self):
        def handle_layers():
            self.render_map_buttons()
            self.update_rectangle_areas()
            self.update_circle_areas()

        with st.expander("Map", expanded=True):
        # st.markdown(f"#### {self.TXT.GET_DATA_TITLE}")
            if self.prev_step_type:
                tab1, tab2 = st.tabs(["Data", f"Search Around {self.prev_step_type.title()}s"])
                with tab1:
                    handle_layers()
                with tab2:
                    self.display_prev_step_selection_table()
            else:
                handle_layers()       

        # return c2_export

    def render_map(self):
        if self.map_disp is not None:
            clear_map_layers(self.map_disp)
        
        self.display_prev_step_selection_marker()

        # feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker] if fg is not None]
        feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker , self.map_fg_prev_selected_marker] if fg is not None]
        
        if self.fig_color_bar and self.step_type == Steps.EVENT:
            st.caption("ℹ️ Marker size is associated with Earthquake magnitude")
        
        c1, c2 = st.columns([18,1])
        with c1:
            self.map_output = st_folium(
                self.map_disp, 
                key=f"map_{self.map_id}",
                feature_group_to_add=feature_groups, 
                use_container_width=True, 
                # height=self.map_height
            )


        with c2:
            if self.fig_color_bar:
                st.pyplot(self.fig_color_bar)

        self.watch_all_drawings(get_selected_areas(self.map_output))

        # @IMPORTANT NOTE: Streamlit-Folium does not provide a direct way to tag a Marker with
        #                  some metadata, including adding an id. The options are using PopUp
        #                  window or tooltips. Here, we have embedded a line at the bottom of the
        #                  popup to be able to get the Event/Station Ids as well as the type of 
        #                  the marker, ie, event or station.
        if self.map_output and self.map_output.get('last_object_clicked') is not None:
            last_clicked = self.map_output['last_object_clicked_popup']

            if isinstance(last_clicked, str):
                idx_info = last_clicked.splitlines()[-1].split()
                step = idx_info[0].lower()
                idx  = int(idx_info[1])
                if step == self.step_type:
                    self.clicked_marker_info = self.marker_info[idx]
                
            else:
                self.clicked_marker_info = None

        if self.warning:
            st.warning(self.warning)
        
        if self.error:
            st.error(self.error)


    def render_marker_select(self):
        def handle_marker_select():
            selected_data = self.get_selected_marker_info()

            if 'is_selected' not in self.df_markers.columns:
                self.df_markers['is_selected'] = False
                
            try:
                if self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected']:
                    st.success(selected_data)
                else:
                    st.warning(selected_data)

                if self.clicked_marker_info['step'] == self.step_type:
                    if st.button("Add to Selection", key=self.get_key_element("Add to Selection")):
                        self.sync_df_markers_with_df_edit()
                        self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected'] = True
                        self.refresh_map_selection()
                        return
            

                if self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected']:
                    if st.button("Unselect", key=self.get_key_element("Unselect")):
                        self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected'] = False
                        # map_component.clicked_marker_info = None
                        # map_component.map_output["last_object_clicked"] = None
                        self.refresh_map_selection()
                        return

            except KeyError:
                print("Selected map marker not found")

        def map_tools_card():
            if not self.df_markers.empty:
                # st.markdown(self.TXT.SELECT_MARKER_TITLE)
                st.info(self.TXT.SELECT_MARKER_MSG)
                if self.clicked_marker_info:
                    handle_marker_select()

            else:                
                st.warning("No data available.")
                    
        # if not self.df_markers.empty:
        map_tools_card()
            # create_card(None, False, map_tools_card)


    def render_data_table(self, c5_map):
        if self.df_markers.empty:
            st.warning("No data available.")
        else:
            st.info(self.TXT.SELECT_DATA_TABLE_MSG)
            cols = self.df_markers.columns
            orig_cols   = [col for col in cols if col != 'is_selected']
            ordered_col = ['is_selected'] + orig_cols

            config = {col: {'disabled': True} for col in orig_cols}

            if 'is_selected' not in self.df_markers.columns:
                self.df_markers['is_selected'] = False
            config['is_selected']  = st.column_config.CheckboxColumn(
                'Select'
            )
            
            state_key = f'initial_df_markers_{self.stage}'

            # Store the initial state in the session if not already stored
            if  state_key not in st.session_state:
                st.session_state[state_key] = self.df_markers.copy()

            def data_table_view():
                c1, c2, c3, c4, c5, c6 = st.columns([1,1,1,1,1,1])
                with c1:
                    st.write(f"Total Number of {self.TXT.STEP.title()}s: {len(self.df_markers)}")
                with c2:
                    if st.button("Select All", key=self.get_key_element("Select All")):
                        self.df_markers['is_selected'] = True
                with c3:
                    if st.button("Unselect All", key=self.get_key_element("Unselect All")):
                        self.df_markers['is_selected'] = False


                self.df_data_edit = st.data_editor(self.df_markers, hide_index = True, column_config=config, column_order = ordered_col, key=self.get_key_element("Data Table"))           
                

                if len(self.df_data_edit) != len(st.session_state[state_key]):
                    has_changed = True
                else:
                    has_changed = not self.df_data_edit.equals(st.session_state[state_key])
                    
                    if has_changed:
                        df_sorted_new = self.df_data_edit.sort_values(by=self.df_data_edit.columns.tolist()).reset_index(drop=True)
                        df_sorted_old = st.session_state[state_key].sort_values(by=st.session_state[state_key].columns.tolist()).reset_index(drop=True)
                        has_changed = not df_sorted_new.equals(df_sorted_old)

                if has_changed:
                    st.session_state[state_key] = self.df_data_edit.copy()  # Save the unsorted version to preserve user sorting
                    self.sync_df_markers_with_df_edit()
                    self.refresh_map_selection()

            data_table_view()
           
        with c5_map:
            # if (not self.df_markers.empty and len(self.df_markers[self.df_markers['is_selected']]) > 0):
            is_disabled = self.df_markers.empty
            if not is_disabled:                
                is_disabled = 'is_selected' not in self.df_markers.columns
                if 'is_selected' in list(self.df_markers.columns):
                    is_disabled = len(self.df_markers[self.df_markers['is_selected']]) == 0
                else:
                    is_disabled = True
                    

            st.download_button(
                f"Download Selected", 
                key=self.get_key_element(f"Download Selected {self.TXT.STEP.title()}s"),
                data=self.export_xml_bytes(export_selected=True),
                file_name = f"{self.TXT.STEP}s_selected.xml",
                mime="application/xml",
                disabled=is_disabled
            )
        # create_card(self.TXT.SELECT_DATA_TABLE_TITLE, False, data_table_view)


    def render(self):

        if self.step_type == Steps.EVENT:
            c2_export = self.event_filter()

        if self.step_type == Steps.STATION:
            c2_export = self.station_filter()


        self.get_prev_step_df()

        self.render_map()

        # c1_top, c2_top = st.columns([2,1])

        # with c2_top:
        #     c2_export = self.render_map_right_menu()

        # with c1_top:
        #     self.render_map()

        if not self.df_markers.empty:
            c1_bot, c2_bot = st.columns([1,3])

            with c1_bot:
                with st.expander(self.TXT.SELECT_MARKER_TITLE, expanded = not self.df_markers.empty):
                    self.render_marker_select()

            with c2_bot:
                with st.expander(self.TXT.SELECT_DATA_TABLE_TITLE, expanded = not self.df_markers.empty):
                    self.render_data_table(c2_export)

        
        # if not self.df_markers.empty:
        #     st.header(self.TXT.SELECT_DATA_TITLE)
        #     tab1, tab2 = st.tabs(["📄 Table", "🌍 Map"])
        #     with tab1:
        #         st.write(self.TXT.SELECT_DATA_TABLE_MSG)
        #         self.render_data_table()

        #     with tab2:
        #         st.write(self.TXT.SELECT_MARKER_MSG)
        #         self.render_marker_select()

            # c21, c22 = st.columns([2,1])            
            # with c22:
            #     self.render_marker_select()

            # with c21:
            #     self.render_data_table()



