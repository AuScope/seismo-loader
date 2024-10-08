from typing import List, Any, Optional, Union
from copy import deepcopy
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta

from obspy.core.inventory import Inventory
from obspy.core.event import Catalog
from obspy.clients.fdsn.header import FDSNException


from seismic_data.ui.components.card import create_card
from seismic_data.ui.components.map import create_map, add_area_overlays, add_data_points, clear_map_layers, clear_map_draw
from seismic_data.ui.pages.helpers.common import get_selected_areas

from seismic_data.service.stations import get_station_data, station_response_to_df
from seismic_data.service.events import event_response_to_df

from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint
from seismic_data.models.common import CircleArea, RectangleArea

from seismic_data.enums.config import GeoConstraintType
from seismic_data.enums.ui import Steps

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
                refresh_map(reset_areas=False,clear_draw=True)


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
                refresh_map(reset_areas=False,clear_draw=True)

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
    map_fg_area =None
    map_fg_marker =None
    map_fg_selected_event_marker =None
    map_height = 500
    map_output = None
    df_stations: pd.DataFrame = pd.DataFrame()
    inventories: List[Inventory]
    marker_info = None
    clicked_marker_info = None
    warning: str = None
    error: str = None
    stage=0

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.inventories=[]
        st.session_state.prev_station_drawings = []        
        if self.map_disp is None:
            self.map_disp = create_map()

    def display_selected_events(self, catalogs: List[Catalog]):
        self.warning = None
        self.error   = None

        df_events = event_response_to_df(catalogs)
        if not df_events.empty:
            cols = df_events.columns                
            cols_to_disp = {c:c.capitalize() for c in cols }
            self.map_fg_selected_event_marker, _ = add_data_points( df_events ,cols_to_disp, step=Steps.EVENT,selected_idx=[], col_color="magnitude")

    def handle_get_stations(self):
        self.warning = None
        self.error   = None
        try:
            self.inventories = get_station_data(self.settings.model_dump_json())
            if self.inventories:
                self.df_stations = station_response_to_df(self.inventories)
                
                if not self.df_stations.empty:
                    cols = self.df_stations.columns
                    cols_to_disp = {c:c.capitalize() for c in cols }
                    cols_to_disp.pop("detail")
                    self.map_fg_marker, self.marker_info = add_data_points( self.df_stations, cols_to_disp, step=Steps.STATION, selected_idx=[], col_color=None)

                else:
                    self.warning = "No stations found for the selected range."
            else:
                self.error = "No data available."
                    
        # except FDSNException as e:
        #     print (f"Invalid request: {str(e)}. Please check your input parameters, such as longitude and latitude.")
        #     self.error = f"Invalid request: {str(e)}. Please check your input parameters, such as longitude and latitude."
        except Exception as e:
            print(f"An unexpected error occurred: {str(e)}")
            self.error = f"An unexpected error occurred: {str(e)}"
        

    def update_selected_inventories(self):
        self.settings.station.selected_invs = None
        is_init = False
        for idx, row in self.df_stations[self.df_stations['is_selected']].iterrows():
            if not is_init:
                self.settings.station.selected_invs = self.inventories.select(station=row["station"])
                is_init = True
            else:
                self.settings.station.selected_invs += self.inventories.select(station=row["station"])


    def handle_update_data_points(self, selected_idx):   
        if not self.df_stations.empty:
            cols = self.df_stations.columns                
            cols_to_disp = {c:c.capitalize() for c in cols }
            cols_to_disp.pop("detail")
            self.map_disp, self.marker_info = add_data_points(
                self.df_stations, cols_to_disp, step=Steps.STATION, selected_idx=selected_idx, col_color=None
            )
        else:
            self.warning = "No station found for the selected range."



    def refresh_map(self, reset_areas = False, selected_idx = None, clear_draw = False):
        
        if reset_areas:
            self.settings.station.geo_constraint = []
        else:
            self.settings.station.geo_constraint.extend(self.areas_current)

        self.map_fg_area= add_area_overlays(areas=self.settings.station.geo_constraint)  

       
        if selected_idx:
            self.handle_update_data_points(selected_idx)
        elif len(self.settings.station.geo_constraint) > 0:
            self.handle_get_stations()

        self.areas_current=[]

        if clear_draw:       
            clear_map_draw(self.map_disp)

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
            # self.map_fg_marker= None
            # self.map_fg_area= None
            # self.inventories=[]
            # self.df_stations = pd.DataFrame()                 
            self.refresh_map(reset_areas=True,clear_draw=True)

    def render_map(self,stage):
        self.stage = stage

        if self.map_disp is None:
            self.map_disp = create_map()

        if self.stage == 2 and len(self.settings.event.selected_catalogs) > 0:    
            self.display_selected_events(self.settings.event.selected_catalogs)

        if self.map_disp is not None:
            clear_map_layers(self.map_disp)


        feature_groups = [fg for fg in [self.map_fg_area, self.map_fg_marker , self.map_fg_selected_event_marker] if fg is not None]

        self.map_output = create_card(
                None,
                True,
                st_folium, 
                self.map_disp, 
                key="new",
                feature_group_to_add=feature_groups, 
                use_container_width=True, 
                height=self.map_height
            )      
        
        current_drawings = get_selected_areas(self.map_output)

        if 'prev_station_drawings' not in st.session_state:
            st.session_state.prev_station_drawings = []

        if len(current_drawings) > len(st.session_state.prev_station_drawings):
            new_shape = current_drawings[-1]  
            st.session_state.prev_station_drawings = current_drawings
            self.areas_current.append(new_shape)  

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
    prev_min_radius : float
    prev_max_radius : float

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.df_data_edit = None
        self.prev_min_radius = None  
        self.prev_max_radius = None  

    def get_selected_idx(self, df_data):
        if df_data.empty:
            return []
        
        mask = df_data['is_selected']
        return df_data[mask].index.tolist()
    
    def sync_df_station_with_df_edit(self, df_station):
        if self.df_data_edit is None:
            # st.error("No data has been edited yet. Please make a selection first.")
            return df_station

        if 'is_selected' not in self.df_data_edit.columns:
            # st.error("'is_selected' column is missing from the edited data.")
            return df_station
                
        df_station['is_selected'] = self.df_data_edit['is_selected']
        return df_station
    

    def refresh_map_selection(self, map_component):
        selected_idx = self.get_selected_idx(map_component.df_stations)
        map_component.update_selected_inventories()
        map_component.refresh_map(reset_areas=False, selected_idx=selected_idx)

    def station_table_view(self, map_component):
        create_card("List of Stations", False, lambda: self.display_stations(map_component))

    def display_stations(self, map_component):
        cols = map_component.df_stations.columns
        orig_cols = [col for col in cols if col != 'is_selected']
        ordered_col = ['is_selected'] + orig_cols

        config = {col: {'disabled': True} for col in orig_cols}

        if 'is_selected' not in map_component.df_stations.columns:
            map_component.df_stations['is_selected'] = False
        config['is_selected'] = st.column_config.CheckboxColumn('Select')

        c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
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

        self.df_data_edit = st.data_editor(
            map_component.df_stations,
            hide_index=True,
            column_config=config,
            column_order=ordered_col
        )

    def display_selected_events(self, map_component):
        df_events = event_response_to_df(self.settings.event.selected_catalogs)
        if df_events.empty:
            st.write("No selected events")
        else:
            with st.container():
                self.area_from_selected_events_card(map_component.refresh_map)
                st.write(f"Total Number of Selected Events: {len(df_events)}")
                st.dataframe(df_events, use_container_width=True)

            # map_component.refresh_map()

    def area_from_selected_events_card(self, refresh_map):

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

        st.write("Define an area around the selected events.")
        c1, c2, c3 = st.columns([1, 1, 1])

        with c1:
            min_radius_str = st.text_input("Minimum radius (km)", value="0")
        with c2:
            max_radius_str = st.text_input("Maximum radius (km)", value="1000")

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
            if st.button("Draw Area"):
                if self.prev_min_radius is None or self.prev_max_radius is None or min_radius != self.prev_min_radius or max_radius != self.prev_max_radius:
                    self.update_area_from_selected_events(min_radius, max_radius, refresh_map)
                    self.prev_min_radius = min_radius
                    self.prev_max_radius = max_radius
                    st.rerun()

    def update_area_from_selected_events(self, min_radius, max_radius, refresh_map):
        min_radius_value = float(min_radius) * 1000
        max_radius_value = float(max_radius) * 1000
        df_events = event_response_to_df(self.settings.event.selected_catalogs)

        updated_constraints = []

        for geo_constraint in self.settings.station.geo_constraint:
            if geo_constraint.geo_type == GeoConstraintType.CIRCLE:
                lat, lng = geo_constraint.coords.lat, geo_constraint.coords.lng
                matching_event = df_events[(df_events['latitude'] == lat) & (df_events['longitude'] == lng)]

                if not matching_event.empty:
                    geo_constraint.coords.min_radius = min_radius_value
                    geo_constraint.coords.max_radius = max_radius_value
            updated_constraints.append(geo_constraint)

        for _, row in df_events.iterrows():
            lat, lng = row['latitude'], row['longitude']
            if not any(
                geo.geo_type == GeoConstraintType.CIRCLE and geo.coords.lat == lat and geo.coords.lng == lng
                for geo in updated_constraints
            ):
                new_donut = CircleArea(lat=lat, lng=lng, min_radius=min_radius_value, max_radius=max_radius_value)
                geo = GeometryConstraint(geo_type=GeoConstraintType.CIRCLE, coords=new_donut)
                updated_constraints.append(geo)

        self.settings.station.geo_constraint = updated_constraints
        refresh_map(reset_areas=False)

    def render(self, map_component: StationMap, stage):
        """
        c2_top is the location beside the map
        """
        c1_top, c2_top = st.columns([2,1])

        with c2_top:
            create_card(None, False, map_component.render_top_buttons)

        with c1_top:
            map_component.render_map(stage)
            if not map_component.df_stations.empty:
                self.station_table_view(map_component)

        with c2_top:
            def handle_marker_select():                
                # st.write(map_component.clicked_marker_info)
                info = map_component.clicked_marker_info
                # selected_station = f"No {info['id']}: {info['Network']}, {info['Station']},{info['Location']},{info['Channel']}, {info['Depth']}"
                selected_station = f"No {info['id']}: {info['Network']}, {info['Station']}"

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

            if stage == 2:
                create_card("List of Selected Events", False, lambda: self.display_selected_events(map_component))

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

    def render(self,stage):
        st.sidebar.header("Station Filters")
        with st.sidebar:
            self.filter_menu.render(self.map_component.refresh_map)

        self.map_component = self.station_select.render(self.map_component,stage=stage)

