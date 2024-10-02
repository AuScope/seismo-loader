from typing import List, Any, Optional, Union
from copy import deepcopy
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta

from obspy.core.inventory import Inventory
from obspy.core.event import Catalog


from seismic_data.ui.components.card import create_card
from seismic_data.ui.components.map import create_map, add_data_points
from seismic_data.ui.pages.helpers.common import get_selected_areas

from seismic_data.service.stations import get_station_data, station_response_to_df
from seismic_data.service.events import event_response_to_df

from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint
from seismic_data.models.common import CircleArea, RectangleArea

from seismic_data.enums.config import GeoConstraintType

# Sidebar date input

class StationFilterMenu:

    settings: SeismoLoaderSettings
    df_rect: None
    df_circ: None

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

        new_geo = [
            area for area in self.settings.station.geo_constraint
            if area.geo_type != geo_type
        ]
        new_geo.extend(add_geo)
        self.settings.station.geo_constraint = new_geo

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
                print(original_df_rect)
                print(self.df_rect)
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
        self.settings.station.network = st.text_input("Enter Network", "_GSN")
        self.settings.station.station = st.text_input("Enter Station", "*")
        self.settings.station.location = st.text_input("Enter Location", "*")
        self.settings.station.channel = st.text_input("Enter Channel", "*")

        
        self.update_rectangle_areas(refresh_map)
        self.update_circle_areas(refresh_map)

class StationMap:
    settings: SeismoLoaderSettings
    areas_current: List[Union[RectangleArea, CircleArea]] = []
    map_disp = None
    map_height = 500
    map_output = None
    df_stations: pd.DataFrame = pd.DataFrame()
    Inventories: List[Inventory]
    marker_info = None
    clicked_marker_info = None
    warning: str = None
    error: str = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings

    def display_selected_events(self, catalogs: List[Catalog]):
        self.warning = None
        self.error   = None
        is_original = False

        df_events = event_response_to_df(catalogs)
        if not df_events.empty:
            cols = df_events.columns                
            cols_to_disp = {c:c.capitalize() for c in cols }
            _, _ = add_data_points(self.map_disp, df_events ,cols_to_disp,selected_idx=[], col_color="magnitude", is_original=is_original)


    def handle_get_stations(self):
        self.warning = None
        self.error   = None

        self.Inventories = get_station_data(self.settings.model_dump_json())
        if self.Inventories:
            self.df_stations = station_response_to_df(self.Inventories)
            
            if not self.df_stations.empty:
                cols = self.df_stations.columns                
                cols_to_disp = {c:c.capitalize() for c in cols }
                self.map_disp, self.marker_info = add_data_points(self.map_disp, self.df_stations,cols_to_disp,selected_idx=[], col_color=None, is_station=True)
            else:
                self.warning = "No stations found for the selected range."
        else:
            self.error = "No data available."


    def update_selected_inventories(self):
        self.settings.station.selected_invs = []
        for i, station in enumerate(self.Inventories):
            if self.df_stations.loc[i, 'is_selected']:
                self.settings.station.selected_invs.append(station)


    def handle_update_data_points(self, selected_idx):
    
        if not self.df_stations.empty:
            cols = self.df_stations.columns                
            cols_to_disp = {c:c.capitalize() for c in cols }
            self.map_disp, self.marker_info = add_data_points(self.map_disp, self.df_stations, cols_to_disp, selected_idx, col_color=None,is_station=True)
        else:
            self.warning = "No station found for the selected range."



    def refresh_map(self, reset_areas = False, selected_idx = None, rerun = False):
        if reset_areas:
            self.settings.station.geo_constraint = []
        else:
            self.settings.station.geo_constraint.extend(self.areas_current)

        self.map_disp = create_map(areas=self.settings.station.geo_constraint)
        if selected_idx:
            self.handle_update_data_points(selected_idx)
        elif len(self.settings.station.geo_constraint) > 0:
            self.handle_get_stations()

        if len(self.settings.event.selected_catalogs) > 0:    
            self.display_selected_events(self.settings.event.selected_catalogs)

        if rerun:
            st.rerun()
            
    def render_top_buttons(self):
        st.markdown("#### Get Stations")
        c11, c22 = st.columns([1,1])
        with c11:
            get_station_clicked = st.button("Get Stations")
        with c22:
            clear_prev_stations_clicked = st.button("Clear All Selections")

        if get_station_clicked:
            self.refresh_map(reset_areas=False)

        if clear_prev_stations_clicked:
            self.refresh_map(reset_areas=True)

    def render_map(self):
        if not self.map_disp:
            self.refresh_map(reset_areas=True)

        self.map_output = create_card(
                None,
                True,
                st_folium, 
                self.map_disp, 
                use_container_width=True, 
                height=self.map_height
            )
        
        self.areas_current = get_selected_areas(self.map_output)
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

class StationSelect:

    settings: SeismoLoaderSettings
    df_data_edit: pd.DataFrame = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings

    def get_selected_idx(self, df_data):
        if df_data.empty:
            return []
        
        mask = df_data['is_selected']
        return df_data[mask].index.tolist()
    
    def sync_df_station_with_df_edit(self, df_station):
        df_station['is_selected'] = self.df_data_edit['is_selected']
        return df_station
    

    def refresh_map_selection(self, map_component):
        selected_idx = self.get_selected_idx(map_component.df_stations)
        map_component.update_selected_inventories()
        map_component.refresh_map(reset_areas=False, selected_idx=selected_idx, rerun = True)


    def render(self, map_component: StationMap):
        """
        c2_top is the location beside the map
        """
        c1_top, c2_top = st.columns([2,1])

        with c2_top:
            create_card(None, False, map_component.render_top_buttons)

        with c1_top:
            map_component.render_map()

        with c2_top:
            def handle_marker_select():                
                # st.write(map_component.clicked_marker_info)
                info = map_component.clicked_marker_info
                selected_station = f"No {info['id']}: {info['Network']}, {info['Station']},{info['Location']},{info['Channel']}, {info['Depth']}"

                if 'is_selected' not in map_component.df_stations.columns:
                    map_component.df_stations['is_selected'] = False

                if map_component.df_stations.loc[map_component.clicked_marker_info['id'] - 1, 'is_selected']:
                    st.success(selected_station)
                else:
                    st.warning(selected_station)

                if st.button("Add to Selection"):
                    map_component.df_stations = self.sync_df_station_with_df_edit(map_component.df_stations)
                    map_component.df_stations.loc[map_component.clicked_marker_info['id'] - 1, 'is_selected'] = True                                             
                    self.refresh_map_selection(map_component)
                    return
                

                if map_component.df_stations.loc[map_component.clicked_marker_info['id'] - 1, 'is_selected']:
                    if st.button("Unselect"):
                        map_component.df_stations.loc[map_component.clicked_marker_info['id'] - 1, 'is_selected'] = False
                        # map_component.clicked_marker_info = None
                        # map_component.map_output["last_object_clicked"] = None
                        self.refresh_map_selection(map_component)
                        return

            def map_tools_card():
                if not map_component.df_stations.empty:
                    st.markdown("#### Select Stations from map")
                    st.write("Click on a marker and add the station or simply select from the Station table")
                    if map_component.clicked_marker_info:
                        handle_marker_select()
                        
            if not map_component.df_stations.empty:
                create_card(None, False, map_tools_card)


        # Show Stations in the table
        if not map_component.df_stations.empty:
            cols = map_component.df_stations.columns
            orig_cols   = [col for col in cols if col != 'is_selected']
            ordered_col = ['is_selected'] + orig_cols

            config = {col: {'disabled': True} for col in orig_cols}

            if 'is_selected' not in map_component.df_stations.columns:
                map_component.df_stations['is_selected'] = False
            config['is_selected']  = st.column_config.CheckboxColumn(
                'Select'
            )

            def station_table_view():
                c1, c2, c3, c4 = st.columns([1,1,1,3])
                with c1:
                    st.write(f"Total Number of Stations: {len(map_component.df_stations)}")
                with c2:
                    if st.button("Select All"):
                        map_component.df_stations['is_selected'] = True
                with c3:
                    if st.button("Unselect All"):
                        map_component.df_stations['is_selected'] = False
                with c4:
                    if st.button("Refresh Map"):
                        map_component.df_stations = self.sync_df_station_with_df_edit(map_component.df_stations)
                        self.refresh_map_selection(map_component)

                self.df_data_edit = st.data_editor(map_component.df_stations, hide_index = True, column_config=config, column_order = ordered_col)           
            create_card("List of Stationss", False, station_table_view)

        return map_component


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

        self.map_component = self.station_select.render(self.map_component)

