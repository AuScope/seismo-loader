from typing import List, Any, Optional, Union
from copy import deepcopy
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta

from seismic_data.ui.components.card import create_card
from seismic_data.ui.components.map import create_map, add_data_points
from seismic_data.ui.pages.helpers.common import get_selected_areas

from seismic_data.service.stations import get_station_data, station_response_to_df

from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint
from seismic_data.models.common import CircleArea, RectangleArea

from seismic_data.enums.config import GeoConstraintType

# Sidebar date input

class StationFilterMenu:

    settings: SeismoLoaderSettings
    df_rect: None
    df_circ: None
    df_donut: None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings

    def update_filter_geometry(self, df, geo_type: GeoConstraintType):
        add_geo = []
        for _, row in df.iterrows():
            coords = row.to_dict()
            if geo_type == GeoConstraintType.BOUNDING:
                add_geo.append(GeometryConstraint(coords=RectangleArea(**coords)))
            if geo_type == GeoConstraintType.CIRCLE:
                add_geo.append(GeometryConstraint(coords=CircleArea(**coords)))

        new_geo = []
        for area in self.settings.station.geo_constraint:
            if area.geo_type != geo_type:
                new_geo.append(area)
        self.settings.station.geo_constraint.extend(new_geo)

    def update_circle_areas(self, refresh_map):
        lst_circ = [area.coords.model_dump() for area in self.settings.station.geo_constraint
                    if area.geo_type == GeoConstraintType.CIRCLE ]

        if lst_circ:
            st.write(f"Circle Areas")
            original_df_circ = pd.DataFrame(lst_circ, columns=CircleArea.model_fields)
            self.df_circ = st.data_editor(original_df_circ, key=f"circ_area")

            circ_changed = not original_df_circ.equals(self.df_circ)

            if circ_changed:
                self.update_filter_geometry(self.df_circ, GeoConstraintType.CIRCLE)
                refresh_map(reset_areas=False)
                st.rerun()


    def update_rectangle_areas(self, refresh_map):
        lst_rect = [area.coords.model_dump() for area in self.settings.station.geo_constraint
                    if isinstance(area.coords, RectangleArea) ]
        if lst_rect:
            st.write(f"Rectangle Areas")
            original_df_rect = pd.DataFrame(lst_rect, columns=RectangleArea.model_fields)
            self.df_rect = st.data_editor(original_df_rect, key=f"rect_area")

            rect_changed = not original_df_rect.equals(self.df_rect)

            if rect_changed:
                self.update_filter_geometry(self.df_rect, GeoConstraintType.BOUNDING)
                refresh_map(reset_areas=False)
                st.rerun()

    def render(self, refresh_map):
        """
        refresh_map is a function that refreshes the map (see StationMap).
        """
        st.header("Select Date Range")
        self.settings.station.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=7))
        self.settings.station.date_config.end_time   = st.date_input("End Date", datetime.now())

        if self.settings.station.date_config.start_time > self.settings.station.date_config.end_time:
            st.error("Error: End Date must fall after Start Date.")

        st.header("Filter SNCL")
        self.settings.station.network = st.text_input("Enter Network", "*")
        self.settings.station.station = st.text_input("Enter Station", "*")
        self.settings.station.location = st.text_input("Enter Location", "*")
        self.settings.station.channel = st.text_input("Enter Channel", "*")

        
        self.update_rectangle_areas(refresh_map)
        self.update_circle_areas(refresh_map)

class StationMap:
    settings: SeismoLoaderSettings
    areas_current: List[Union[RectangleArea, CircleArea]] = []
    map_disp = None
    map_height = 600
    df_stations: pd.DataFrame = pd.DataFrame()
    marker_info = None
    clicked_marker_info = None
    warning: str = None
    error: str = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings

    def handle_get_stations(self):
        self.warning = None
        self.error   = None

        data = get_station_data(self.settings.model_dump_json())
        if data:
            self.df_stations = station_response_to_df(data)
            
            if not self.df_stations.empty:
                cols = self.df_stations.columns                
                cols_to_disp = {c:c.capitalize() for c in cols }
                self.map_disp, self.marker_info = add_data_points(self.map_disp, self.df_stations,cols_to_disp,selected_idx=[], col_color=None)
            else:
                self.warning = "No stations found for the selected range."
        else:
            self.error = "No data available."


    def refresh_map(self, reset_areas = False):
        if reset_areas:
            self.settings.station.geo_constraint = []
        else:
            self.settings.station.geo_constraint.extend(self.areas_current)

        self.map_disp = create_map(areas=self.settings.station.geo_constraint)
        if len(self.settings.station.geo_constraint) > 0:
            self.handle_get_stations()

    
    
    def render(self):
        if not self.map_disp:
            self.refresh_map(reset_areas=True)

        c1_top, c2_top = st.columns([1, 1])
        with c1_top:
            get_station_clicked = st.button("Get Stations")
        with c2_top:
            clear_prev_stations_clicked = st.button("Clear All Selections")

        if get_station_clicked:
            self.refresh_map(reset_areas=False)

        if clear_prev_stations_clicked:
            self.refresh_map(reset_areas=True)

        output = create_card(
            None, 
            st_folium, 
            self.map_disp, 
            use_container_width=True, 
            height=self.map_height
        )
        self.areas_current = get_selected_areas(output)
        if output and output.get('last_object_clicked') is not None:
            clicked_lat_lng = (output['last_object_clicked'].get('lat'), output['last_object_clicked'].get('lng'))
            if clicked_lat_lng in self.marker_info:
                self.clicked_marker_info = self.marker_info[clicked_lat_lng]

        if self.warning:
            st.warning(self.warning)
        
        if self.error:
            st.error(self.error)

        st.write(self.clicked_marker_info)

class StationSelect:

    settings: SeismoLoaderSettings
    df_data_edit: pd.DataFrame = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings


    def render(self, df_data):
        # Show Stations in the table
        if not df_data.empty:
            cols = df_data.columns
            orig_cols   = [col for col in cols if col != 'is_selected']
            ordered_col = ['is_selected'] + orig_cols

            config = {col: {'disabled': True} for col in orig_cols}

            df_data['is_selected'] = False     
            config['is_selected']  = st.column_config.CheckboxColumn(
                'Select'
            )
            
            c1, c2, c3 = st.columns([1,1,12])
            with c1:
                st.write(f"Total Number of Stations: {len(df_data)}")
            with c2:
                if st.button("Select All"):
                    df_data['is_selected'] = True
            with c3:
                if st.button("Unselect All"):
                    df_data['is_selected'] = False
            self.df_data_edit = st.data_editor(df_data, hide_index = True, column_config=config, column_order = ordered_col)


class StationComponents:

    settings: SeismoLoaderSettings
    filter_menu: StationFilterMenu
    map_component: StationMap
    station_select: StationSelect

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings      = settings
        self.filter_menu   = StationFilterMenu(settings)
        self.map_component = StationMap(settings)
        self.station_select  = StationSelect(settings)

    def render(self):
        st.sidebar.header("Station Filters")
        with st.sidebar:
            self.filter_menu.render(self.map_component.refresh_map)

        self.map_component.render()
        self.station_select.render(self.map_component.df_stations)


