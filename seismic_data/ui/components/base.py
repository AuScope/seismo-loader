from typing import List, Any, Optional, Union
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta
import uuid
from obspy.core.event import Catalog
from obspy.core.inventory import Inventory

from seismic_data.ui.components.card import create_card
from seismic_data.ui.components.map import create_map, add_area_overlays, add_data_points, clear_map_layers, clear_map_draw,add_map_draw
from seismic_data.ui.pages.helpers.common import get_selected_areas

from seismic_data.service.events import get_event_data, event_response_to_df
from seismic_data.service.stations import get_station_data, station_response_to_df

from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint, EventConfig, StationConfig
from seismic_data.models.common import CircleArea, RectangleArea

from seismic_data.enums.config import GeoConstraintType
from seismic_data.enums.ui import Steps
import json


def event_filter(event: EventConfig):
    st.sidebar.header("Event Filters")
    with st.sidebar:
        st.header("Select Date Range")
        event.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=7))
        event.date_config.end_time   = st.date_input("End Date", datetime.now())

        if event.date_config.start_time > event.date_config.end_time:
            st.error("Error: End Date must fall after Start Date.")

        st.header("Filter Earthquakes")
        event.min_magnitude, event.max_magnitude = st.slider("Min Magnitude", min_value=-2.0, max_value=10.0, value = (2.4,9.0), step=0.1, key="event-pg-mag")
        event.min_depth, event.max_depth = st.slider("Min Depth (km)", min_value=-5.0, max_value=800.0, value=(0.0,500.0), step=1.0, key=f"event-pg-depth")

    return event

def station_filter(station: StationConfig):
    st.sidebar.header("Station Filters")
    with st.sidebar:
        st.header("Select Date Range")
        station.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=7))
        station.date_config.end_time   = st.date_input("End Date", datetime.now())

        if station.date_config.start_time > station.date_config.end_time:
            st.error("Error: End Date must fall after Start Date.")

        st.header("Filter SNCL")
        station.network = st.text_input("Enter Network", "_GSN")
        station.station = st.text_input("Enter Station", "*")
        station.location = st.text_input("Enter Location", "*")
        station.channel = st.text_input("Enter Channel", "*")

    return station

class BaseComponentTexts:
    CLEAR_ALL_MAP_DATA = "Clear All"
    def __init__(self, config_type: Steps):
        if config_type == Steps.EVENT:
            self.BTN_GET_DATA = "Get Events"
            self.SELECT_MARKER_TITLE = "#### Select Events from map"
            self.SELECT_MARKER_MSG   = "Click on a marker and add the event"
            self.SELECT_DATA_TABLE_TITLE = "Select Events from table"

        if config_type == Steps.STATION:
            self.BTN_GET_DATA = "Get Stations"
            self.SELECT_MARKER_TITLE = "#### Select Stations from map"
            self.SELECT_MARKER_MSG   = "Click on a marker and add the station"
            self.SELECT_DATA_TABLE_TITLE = "Select Stations from table"



class BaseComponent:
    settings: SeismoLoaderSettings
    config_type: Steps
    TXT: BaseComponentTexts

    all_current_drawings: List[GeometryConstraint] = []
    all_feature_drawings: List[GeometryConstraint] = []
    map_disp = None
    map_fg_area =None
    map_fg_marker =None
    map_height = 500
    map_output = None
    df_markers: pd.DataFrame = pd.DataFrame()
    catalogs: List[Catalog] = []
    inventories: List[Inventory] = []
    marker_info = None
    clicked_marker_info = None
    warning: str = None
    error: str = None
    df_rect: None
    df_circ: None
    col_color = None

    df_data_edit: pd.DataFrame = None    


    def __init__(self, settings: SeismoLoaderSettings, config_type: Steps):
        self.settings      = settings
        self.config_type   = config_type
        self.map_id = str(uuid.uuid4())        
        self.map_disp = create_map(map_id=self.map_id)
        self.TXT = BaseComponentTexts(config_type)

        if self.config_type == Steps.EVENT:
            self.col_color = "magnitude"
            self.config = self.settings.event
        if self.config_type == Steps.STATION:
            self.col_color = None
            self.config =  self.settings.station


    def get_geo_constraint(self):
        if self.config_type == Steps.EVENT:
            return self.settings.event.geo_constraint
        if self.config_type == Steps.STATION:
            return self.settings.station.geo_constraint
        return None
    
    def set_geo_constraint(self, geo_constraint: List[GeometryConstraint]):
        if self.config_type == Steps.EVENT:
            self.settings.event.geo_constraint = geo_constraint
        if self.config_type == Steps.STATION:
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
            st.write(f"Circle Areas")
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
        if self.config_type == Steps.EVENT:
            self.settings.event.selected_catalogs = []
            for i, event in enumerate(self.catalogs):
                if self.df_markers.loc[i, 'is_selected']:
                    self.settings.event.selected_catalogs.append(event)
            return
        if self.config_type == Steps.STATION:
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
            self.map_fg_marker, self.marker_info = add_data_points( self.df_markers, cols_to_disp, step=self.config_type.value, selected_idx = selected_idx, col_color=self.col_color)
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

           

        if rerun:
            st.rerun()
    # ====================
    # GET DATA
    # ====================
    def handle_get_data(self):
        self.warning = None
        self.error   = None
        
        try:
            if self.config_type == Steps.EVENT:
                self.catalogs = get_event_data(self.settings.model_dump_json())
                if self.catalogs:
                    self.df_markers = event_response_to_df(self.catalogs)

            if self.config_type == Steps.STATION:
                self.inventories = get_station_data(self.settings.model_dump_json())
                if self.inventories:
                    self.df_markers = station_response_to_df(self.inventories)
                
            if not self.df_markers.empty:
                cols = self.df_markers.columns                
                cols_to_disp = {c:c.capitalize() for c in cols }
                if 'detail' in cols_to_disp:
                    cols_to_disp.pop("detail")
                self.map_fg_marker, self.marker_info = add_data_points( self.df_markers, cols_to_disp, step=self.config_type.value, col_color=self.col_color)
            else:
                self.warning = "No data available."

        except Exception as e:
            print(f"An unexpected error occurred: {str(e)}")
            self.error = f"An unexpected error occurred: {str(e)}"

    
    def clear_all_data(self):
        self.map_fg_marker= None
        self.map_fg_area= None
        self.catalogs=[]
        self.df_markers = pd.DataFrame()
        self.all_current_drawings = []
        self.settings.event.geo_constraint = []
        self.settings.station.geo_constraint = []


    def get_selected_marker_info(self):
        info = self.clicked_marker_info
        if self.config_type == Steps.EVENT:
            return f"No {info['id']}: {info['Magnitude']}, {info['Depth']} km, {info['Place']}"
        if self.config_type == Steps.STATION:
            return f"No {info['id']}: {info['Network']}, {info['Station']}"
    # ===================
    # SELECT DATA
    # ===================
    def get_selected_idx(self, df_data):
        if df_data.empty:
            return []
        
        mask = df_data['is_selected']
        return df_data[mask].index.tolist()

    def sync_df_markers_with_df_edit(self):
        if self.df_data_edit is None:
            # st.error("No data has been edited yet. Please make a selection first.")
            return

        if 'is_selected' not in self.df_data_edit.columns:
            # st.error("'is_selected' column is missing from the edited data.")
            return

        self.df_markers['is_selected'] = self.df_data_edit['is_selected']
    
    def refresh_map_selection(self):
        selected_idx = self.get_selected_idx(self.df_markers)
        self.update_selected_data()
        self.refresh_map(reset_areas=False, selected_idx=selected_idx, rerun=True)

    # ===================
    # RENDER
    # ===================
    def render_map_buttons(self):
        st.markdown(f"#### {self.TXT.BTN_GET_DATA}")
        c11, c22 = st.columns([1,1])
        with c11:
            get_data_clicked = st.button(self.TXT.BTN_GET_DATA)
        with c22:
            clear_prev_data_clicked = st.button(self.TXT.CLEAR_ALL_MAP_DATA)

        if get_data_clicked:
            self.refresh_map(reset_areas=False)

        if clear_prev_data_clicked:
            self.clear_all_data()
            self.refresh_map(reset_areas=True, clear_draw=True, rerun=True)

        self.update_rectangle_areas()
        self.update_circle_areas()


    def render_map(self):
        if self.map_disp is not None:
            clear_map_layers(self.map_disp)

        feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker] if fg is not None]
            
        
        self.map_output = create_card(
            None,
            True,
            st_folium, 
            self.map_disp, 
            key=f"map_{self.map_id}",
            feature_group_to_add=feature_groups, 
            use_container_width=True, 
            height=self.map_height,
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

            if st.button("Add to Selection"):
                self.sync_df_markers_with_df_edit()
                self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected'] = True          
                self.refresh_map_selection()
                return
            

            if self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected']:
                if st.button("Unselect"):
                    self.df_markers.loc[self.clicked_marker_info['id'] - 1, 'is_selected'] = False
                    # map_component.clicked_marker_info = None
                    # map_component.map_output["last_object_clicked"] = None
                    self.refresh_map_selection()
                    return

        def map_tools_card():
            if not self.df_markers.empty:
                st.markdown(self.TXT.SELECT_MARKER_TITLE)
                st.write(self.TXT.SELECT_MARKER_MSG)
                if self.clicked_marker_info:
                    handle_marker_select()
                    
        if not self.df_markers.empty:
            create_card(None, False, map_tools_card)


    def render_data_table(self):
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
            c1, c2, c3, c4 = st.columns([1,1,1,3])
            with c1:
                st.write(f"Total Number of Events: {len(self.df_markers)}")
            with c2:
                if st.button("Select All"):
                    self.df_markers['is_selected'] = True
            with c3:
                if st.button("Unselect All"):
                    self.df_markers['is_selected'] = False
            with c4:
                if st.button("Refresh Map"):
                    self.sync_df_markers_with_df_edit()
                    self.refresh_map_selection()

            self.df_data_edit = st.data_editor(self.df_markers, hide_index = True, column_config=config, column_order = ordered_col)           
        create_card(self.TXT.SELECT_DATA_TABLE_TITLE, False, data_table_view)


    def render(self):

        if self.config_type == Steps.EVENT:
            self.settings.event = event_filter(self.settings.event)

        if self.config_type == Steps.STATION:
            self.settings.station = station_filter(self.settings.station)


        c1_top, c2_top = st.columns([2,1])

        with c2_top:
            create_card(None, False, self.render_map_buttons)

        with c1_top:
            self.render_map()
            

        if not self.df_markers.empty:
            c21, c22 = st.columns([2,1])
            with c22:
                self.render_marker_select()

            with c21:
                self.render_data_table()