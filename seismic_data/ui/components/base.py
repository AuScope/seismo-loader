from typing import List, Any, Optional, Union
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta
import uuid
from obspy.core.event import Catalog, read_events
from obspy.core.inventory import Inventory, read_inventory
from io import BytesIO



from seismic_data.ui.components.card import create_card
from seismic_data.ui.components.map import create_map, add_area_overlays, add_data_points, clear_map_layers, clear_map_draw,add_map_draw
from seismic_data.ui.pages.helpers.common import get_selected_areas

from seismic_data.service.events import get_event_data, event_response_to_df
from seismic_data.service.stations import get_station_data, station_response_to_df
from seismic_data.service.seismoloader import convert_radius_to_degrees, convert_degrees_to_radius_meter

from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint, EventConfig, StationConfig
from seismic_data.models.common import CircleArea, RectangleArea

from seismic_data.enums.config import GeoConstraintType, SeismoClients
from seismic_data.enums.ui import Steps
import json


client_options = [f.name for f in SeismoClients]


def event_filter(event: EventConfig):
    st.sidebar.header("Event Filters")
    with st.sidebar:
        selected_client = st.selectbox('Choose a client:', client_options, index=client_options.index(SeismoClients.IRIS.name), key="event-pg-client-event")
        event.client = SeismoClients[selected_client]
        event.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=7), key="event-pg-start-date-event")
        event.date_config.end_time   = st.date_input("End Date", datetime.now(), key="event-pg-end-date-event")

        if event.date_config.start_time > event.date_config.end_time:
            st.error("Error: End Date must fall after Start Date.")
        event.min_magnitude, event.max_magnitude = st.slider("Min Magnitude", min_value=-2.0, max_value=10.0, value = (2.4,9.0), step=0.1, key="event-pg-mag")
        event.min_depth, event.max_depth = st.slider("Min Depth (km)", min_value=-5.0, max_value=800.0, value=(0.0,500.0), step=1.0, key=f"event-pg-depth")

    return event

def station_filter(station: StationConfig):
    st.sidebar.header("Station Filters")
    with st.sidebar:
        selected_client = st.selectbox('Choose a client:', client_options, index=client_options.index(SeismoClients.IRIS.name), key="event-pg-client-station")
        station.client = SeismoClients[selected_client]
        station.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=7), key="event-pg-start-date-station")
        station.date_config.end_time   = st.date_input("End Date", datetime.now(), key="event-pg-end-date-station")

        if station.date_config.start_time > station.date_config.end_time:
            st.error("Error: End Date must fall after Start Date.")

        
        station.network = st.text_input("Enter Network", "_GSN", key="event-pg-net-txt-station")
        station.station = st.text_input("Enter Station", "*", key="event-pg-sta-txt-station")
        station.location = st.text_input("Enter Location", "*", key="event-pg-loc-txt-station")
        station.channel = st.text_input("Enter Channel", "*", key="event-pg-cha-txt-station")

    return station



class BaseComponentTexts:
    CLEAR_ALL_MAP_DATA = "Clear All"
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
            self.SELECT_DATA_TABLE_MSG = "Tick events from the table. Use Refresh Map to view your selected events on the map."

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
            self.SELECT_DATA_TABLE_MSG = "Tick stations from the table. Use Refresh Map to view your selected stations on the map."

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
    df_markers_prev             = pd.DataFrame()


    def __init__(self, settings: SeismoLoaderSettings, step_type: Steps, prev_step_type: Steps, stage: int):
        self.settings       = settings
        self.step_type      = step_type
        self.prev_step_type = prev_step_type
        self.stage          = stage
        self.map_id         = str(uuid.uuid4())
        self.map_disp       = create_map(map_id=self.map_id)
        self.TXT            = BaseComponentTexts(step_type)

        if self.step_type == Steps.EVENT:
            self.col_color = "magnitude"
            self.config = self.settings.event
        if self.step_type == Steps.STATION:
            self.col_color = None
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
            self.df_circ = st.data_editor(original_df_circ, key=f"circ_area")

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
            self.df_rect = st.data_editor(original_df_rect, key=f"rect_area")

            rect_changed = not original_df_rect.equals(self.df_rect)

            if rect_changed:
                self.update_filter_geometry(self.df_rect, GeoConstraintType.BOUNDING, geo_constraint)
                self.refresh_map(reset_areas=False, clear_draw=True)


    def update_selected_data(self):
        if self.step_type == Steps.EVENT:
            self.settings.event.selected_catalogs = Catalog(events=None)
            for i, event in enumerate(self.catalogs):
                if self.df_markers.loc[i, 'is_selected']:
                    self.settings.event.selected_catalogs.append(event)
            return
        if self.step_type == Steps.STATION:
            self.settings.station.selected_invs = None
            is_init = False
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
            cols_to_disp = {c:c.capitalize() for c in cols }
            if 'detail' in cols_to_disp:
                cols_to_disp.pop("detail")
            self.map_fg_marker, self.marker_info = add_data_points( self.df_markers, cols_to_disp, step=self.step_type.value, selected_idx = selected_idx, col_color=self.col_color)
        else:
            self.warning = "No data found."

    def refresh_map(self, reset_areas = False, selected_idx = None, clear_draw = False, rerun = False):

        geo_constraint = self.get_geo_constraint()
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
        elif len(geo_constraint) > 0:
            self.handle_get_data()

        # self.display_prev_step_selection_marker()

        if rerun:
            st.rerun()
        
    # ====================
    # GET DATA
    # ====================
    def handle_get_data(self, is_import: bool = False, uploaded_file = None):
        self.warning = None
        self.error   = None
        
        try:
            if self.step_type == Steps.EVENT:
                # self.catalogs = get_event_data(self.settings.model_dump_json())
                if is_import:
                    self.import_xml(uploaded_file)
                else:
                    self.catalogs = get_event_data(self.settings)
                if self.catalogs:
                    self.df_markers = event_response_to_df(self.catalogs)

            if self.step_type == Steps.STATION:
                # self.inventories = get_station_data(self.settings.model_dump_json())
                if is_import:
                    self.import_xml(uploaded_file)
                else:
                    self.inventories = get_station_data(self.settings)
                if self.inventories:
                    self.df_markers = station_response_to_df(self.inventories)
                
            if not self.df_markers.empty:
                cols = self.df_markers.columns                
                cols_to_disp = {c:c.capitalize() for c in cols }
                if 'detail' in cols_to_disp:
                    cols_to_disp.pop("detail")
                self.map_fg_marker, self.marker_info = add_data_points( self.df_markers, cols_to_disp, step=self.step_type.value, col_color=self.col_color)
            else:
                self.warning = "No data available."

        except Exception as e:
            print(f"An unexpected error occurred: {str(e)}")
            self.error = f"An unexpected error occurred: {str(e)}"

    
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


    def get_selected_marker_info(self):
        info = self.clicked_marker_info
        if self.step_type == Steps.EVENT:
            return f"No {info['id']}: {info['Magnitude']}, {info['Depth']} km, {info['Place']}"
        if self.step_type == Steps.STATION:
            return f"No {info['id']}: {info['Network']}, {info['Station']}"
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
            self.warning = None
            self.error   = None
            col_color = None
            if self.prev_step_type == Steps.EVENT:
                col_color = "magnitude"

            if not self.df_markers_prev.empty:
                cols = self.df_markers_prev.columns
                cols_to_disp = {c:c.capitalize() for c in cols }
                if "detail" in cols_to_disp:
                    cols_to_disp.pop("detail")
                self.map_fg_prev_selected_marker, _ = add_data_points( self.df_markers_prev, cols_to_disp, step=self.prev_step_type.value,selected_idx=[], col_color=col_color)

        
    def display_prev_step_selection_table(self):
        if self.stage > 1:
            if self.df_markers_prev.empty:
                st.write(f"No selected {self.TXT.PREV_STEP}s")
            else:
                # with st.expander(f"Search around {self.TXT.PREV_STEP}", expanded = True):
                self.area_around_prev_step_selections()
                st.write(f"Total Number of Selected {self.TXT.PREV_STEP.title()}s: {len(self.df_markers_prev)}")
                st.dataframe(self.df_markers_prev, use_container_width=True)

    
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
        c1, c2, c3 = st.columns([1, 1, 1])

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

        with c3:
            if st.button("Draw Area", key=self.get_key_element("Draw Area")):
                if self.prev_min_radius is None or self.prev_max_radius is None or min_radius != self.prev_min_radius or max_radius != self.prev_max_radius:
                    self.update_area_around_prev_step_selections(min_radius, max_radius)
                    self.prev_min_radius = min_radius
                    self.prev_max_radius = max_radius
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
        self.refresh_map(reset_areas=False, clear_draw=True)

    # ===================
    # FILES
    # ===================
    def export_xml_bytes(self, export_selected: bool = True):
        if export_selected:
            # self.sync_df_markers_with_df_edit()
            self.update_selected_data()
        with BytesIO() as f:
            if self.step_type == Steps.STATION:                
                inv = self.settings.station.selected_invs if export_selected else self.inventories
                inv.write(f, format='STATIONXML')

            if self.step_type == Steps.EVENT:
                cat = self.settings.event.selected_catalogs if export_selected else self.catalogs
                cat.write(f, format="QUAKEML")
                

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
    # RENDER
    # ===================
    def render_map_buttons(self):
        # st.markdown(f"#### {self.TXT.GET_DATA_TITLE}")
        if self.prev_step_type:
            tab1, tab2, tab3 = st.tabs(["Get Data", "Areas", f"Search Around {self.prev_step_type.title()}s"])
        else:
            tab1, tab2 = st.tabs(["Get Data", "Areas"])

        with tab1:
        # with st.expander(f"Manage Data", expanded = True):
            get_data_clicked = st.button(self.TXT.BTN_GET_DATA, key=self.get_key_element(self.TXT.BTN_GET_DATA))               

            def reset_uploaded_file_processed():
                st.session_state['uploaded_file_processed'] = False

            uploaded_file = st.file_uploader(f"Import {self.TXT.STEP.title()}s from a File", type=["xml"], on_change=lambda:  reset_uploaded_file_processed())
            if uploaded_file and not st.session_state['uploaded_file_processed']:
                self.clear_all_data()
                self.refresh_map(reset_areas=True, clear_draw=True)
                self.handle_get_data(is_import=True, uploaded_file=uploaded_file)
                st.session_state['uploaded_file_processed'] = True

            clear_prev_data_clicked = st.button(self.TXT.CLEAR_ALL_MAP_DATA, key=self.get_key_element(self.TXT.CLEAR_ALL_MAP_DATA))

            if get_data_clicked:
                self.refresh_map(reset_areas=False)

            if clear_prev_data_clicked:
                self.clear_all_data()
                self.refresh_map(reset_areas=True, clear_draw=True, rerun=True)

        # with st.expander(f"Update Selection Area", expanded = True):
        with tab2:
            self.update_rectangle_areas()
            self.update_circle_areas()
            
            if len(self.get_geo_constraint()) == 0 and len(self.all_current_drawings) == 0:
                st.info("There is no defined areas on map. Please first use the map tools to draw an area and get the data.")

        if self.prev_step_type:
            with tab3:
                self.display_prev_step_selection_table()


    def render_map(self):

        if self.map_disp is not None:
            clear_map_layers(self.map_disp)
        
        self.display_prev_step_selection_marker()

        # feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker] if fg is not None]
        feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker , self.map_fg_prev_selected_marker] if fg is not None]
        
        self.map_output = st_folium(
            self.map_disp, 
            key=f"map_{self.map_id}",
            feature_group_to_add=feature_groups, 
            use_container_width=True, 
            height=self.map_height
        )                

        self.all_current_drawings = get_selected_areas(self.map_output)

        if self.map_output and self.map_output.get('last_object_clicked') is not None:
            last_clicked = self.map_output['last_object_clicked']
            if isinstance(last_clicked, dict):
                clicked_lat_lng = (last_clicked.get('lat'), last_clicked.get('lng'))
            elif isinstance(last_clicked, list):
                clicked_lat_lng = (last_clicked[0], last_clicked[1])
            else:
                clicked_lat_lng = (None, None)

            if clicked_lat_lng in self.marker_info:
                self.clicked_marker_info = self.marker_info[clicked_lat_lng]

        if self.warning:
            st.warning(self.warning)
        
        if self.error:
            st.error(self.error)

    def render_marker_select(self):
        def handle_marker_select():
            selected_data = self.get_selected_marker_info()

            if 'is_selected' not in self.df_markers.columns:
                self.df_markers['is_selected'] = False
                
            if self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected']:
                st.success(selected_data)
            else:
                st.warning(selected_data)

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


    def render_data_table(self):
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

            def data_table_view():
                c1, c2, c3, c4, c5, c6 = st.columns([1,1,1,1,1,1])
                with c1:
                    st.write(f"Total Number of {self.TXT.STEP.title()}s: {len(self.df_markers)}")
                with c2:
                    if st.button("Refresh", key=self.get_key_element("Refresh Map")):
                        self.sync_df_markers_with_df_edit()
                        self.refresh_map_selection()
                with c3:
                    if st.button("Select All", key=self.get_key_element("Select All")):
                        self.df_markers['is_selected'] = True
                with c4:
                    if st.button("Unselect All", key=self.get_key_element("Unselect All")):
                        self.df_markers['is_selected'] = False

                with c5:
                    if (len(self.catalogs.events) > 0 or len(self.inventories.get_contents().get('stations')) > 0):
                        st.download_button(
                            f"Download All {self.TXT.STEP.title()}s", 
                            key=self.get_key_element(f"Download All {self.TXT.STEP.title()}s"),
                            data=self.export_xml_bytes(export_selected=False),
                            file_name = f"{self.TXT.STEP}s.xml",
                            mime="application/xml"
                        )

                with c6:
                    if (not self.df_markers.empty and len(self.df_markers[self.df_markers['is_selected']]) > 0):
                        st.download_button(
                            f"Download Selected {self.TXT.STEP.title()}s", 
                            key=self.get_key_element(f"Download Selected {self.TXT.STEP.title()}s"),
                            data=self.export_xml_bytes(export_selected=True),
                            file_name = f"{self.TXT.STEP}s_selected.xml",
                            mime="application/xml"
                        )


                self.df_data_edit = st.data_editor(self.df_markers, hide_index = True, column_config=config, column_order = ordered_col, key=self.get_key_element("Data Table"))           
            
            data_table_view()
        # create_card(self.TXT.SELECT_DATA_TABLE_TITLE, False, data_table_view)


    def render(self):

        if self.step_type == Steps.EVENT:
            self.settings.event = event_filter(self.settings.event)

        if self.step_type == Steps.STATION:
            self.settings.station = station_filter(self.settings.station)


        self.get_prev_step_df()

        tab1, tab2, tab3 = st.tabs(["🌍 Map", "📄 Config", "Code"])
        with tab1:
            c1_top, c2_top = st.columns([2,1])

            with c2_top:
                self.render_map_buttons()

            with c1_top:
                self.render_map()

            with st.expander(self.TXT.SELECT_MARKER_TITLE, expanded = not self.df_markers.empty):
                self.render_marker_select()

            with st.expander(self.TXT.SELECT_DATA_TABLE_TITLE, expanded = not self.df_markers.empty):
                self.render_data_table()

        with tab2:
            st.write("Placeholder for config")

        with tab3:
            st.write("Placeholder for code")
        
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



