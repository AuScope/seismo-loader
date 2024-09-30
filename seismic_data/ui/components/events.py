from typing import List, Any, Optional, Union
from copy import deepcopy
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta

from seismic_data.ui.components.card import create_card
from seismic_data.ui.components.map import create_map, add_data_points
from seismic_data.ui.pages.helpers.common import get_selected_areas

from seismic_data.service.events import get_event_data, event_response_to_df

from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint
from seismic_data.models.common import CircleArea, RectangleArea

from seismic_data.enums.config import GeoConstraintType

# Sidebar date input

class EventFilterMenu:

    settings: SeismoLoaderSettings
    df_rect: None
    df_circ: None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings


    def update_event_filter_geometry(self, df, geo_type: GeoConstraintType):
        add_geo = []
        for _, row in df.iterrows():
            coords = row.to_dict()
            if geo_type == GeoConstraintType.BOUNDING:
                add_geo.append(GeometryConstraint(coords=RectangleArea(**coords)))
            if geo_type == GeoConstraintType.CIRCLE:
                add_geo.append(GeometryConstraint(coords=CircleArea(**coords)))

        new_geo = [
            area for area in self.settings.event.geo_constraint
            if area.geo_type != geo_type
        ]
        new_geo.extend(add_geo)
        self.settings.event.geo_constraint = new_geo

    def update_circle_areas(self, refresh_map):
        lst_circ = [area.coords.model_dump() for area in self.settings.event.geo_constraint
                    if area.geo_type == GeoConstraintType.CIRCLE ]

        if lst_circ:
            st.write(f"Circle Areas")
            original_df_circ = pd.DataFrame(lst_circ, columns=CircleArea.model_fields)
            self.df_circ = st.data_editor(original_df_circ, key=f"circ_area")

            circ_changed = not original_df_circ.equals(self.df_circ)

            if circ_changed:
                self.update_event_filter_geometry(self.df_circ, GeoConstraintType.CIRCLE)
                refresh_map(reset_areas=False)
                st.rerun()


    def update_rectangle_areas(self, refresh_map):
        lst_rect = [area.coords.model_dump() for area in self.settings.event.geo_constraint
                    if isinstance(area.coords, RectangleArea) ]

        if lst_rect:
            st.write(f"Rectangle Areas")
            original_df_rect = pd.DataFrame(lst_rect, columns=RectangleArea.model_fields)
            self.df_rect = st.data_editor(original_df_rect, key=f"rect_area")

            rect_changed = not original_df_rect.equals(self.df_rect)

            if rect_changed:
                self.update_event_filter_geometry(self.df_rect, GeoConstraintType.BOUNDING)
                refresh_map(reset_areas=False)
                st.rerun()

    def render(self, refresh_map):
        """
        refresh_map is a function that refreshes the map (see EventMap).
        """
        st.header("Select Date Range")
        self.settings.event.date_config.start_time = st.date_input("Start Date", datetime.now() - timedelta(days=7))
        self.settings.event.date_config.end_time   = st.date_input("End Date", datetime.now())

        if self.settings.event.date_config.start_time > self.settings.event.date_config.end_time:
            st.error("Error: End Date must fall after Start Date.")

        st.header("Filter Earthquakes")
        self.settings.event.min_magnitude, self.settings.event.max_magnitude = st.slider("Min Magnitude", min_value=-2.0, max_value=10.0, value = (2.4,9.0), step=0.1, key="event-pg-mag")
        self.settings.event.min_depth, self.settings.event.max_depth = st.slider("Min Depth (km)", min_value=-5.0, max_value=800.0, value=(0.0,500.0), step=1.0, key=f"event-pg-depth")
        
        self.update_rectangle_areas(refresh_map)
        self.update_circle_areas(refresh_map)

class EventMap:
    settings: SeismoLoaderSettings
    areas_current: List[Union[RectangleArea, CircleArea]] = []
    map_disp = None
    map_height = 600
    map_output = None
    df_events: pd.DataFrame = pd.DataFrame()
    marker_info = None
    clicked_marker_info = None
    warning: str = None
    error: str = None

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings

    def handle_get_events(self):
        self.warning = None
        self.error   = None

        data = get_event_data(self.settings.model_dump_json())
        if data:
            # Convert records to a DataFrame (optional)
            self.df_events = event_response_to_df(data)
            
            if not self.df_events.empty:
                cols = self.df_events.columns                
                cols_to_disp = {c:c.capitalize() for c in cols }
                self.map_disp, self.marker_info = add_data_points(self.map_disp, self.df_events, cols_to_disp, col_color='magnitude')
            else:
                self.warning = "No earthquakes found for the selected magnitude and depth range."
        else:
            self.error = "No data available."


    def handle_update_data_points(self, selected_idx):
        if not self.df_events.empty:
            cols = self.df_events.columns                
            cols_to_disp = {c:c.capitalize() for c in cols }
            self.map_disp, self.marker_info = add_data_points(self.map_disp, self.df_events, cols_to_disp, selected_idx, col_color='magnitude')
        else:
            self.warning = "No earthquakes found for the selected magnitude and depth range."


    

    def refresh_map(self, reset_areas = False, selected_idx = None, rerun = False):
        if reset_areas:
            self.settings.event.geo_constraint = []
        else:
            self.settings.event.geo_constraint.extend(self.areas_current)

        self.map_disp = create_map(areas=self.settings.event.geo_constraint)
        if selected_idx:
            self.handle_update_data_points(selected_idx)
        elif len(self.settings.event.geo_constraint) > 0:
            self.handle_get_events()

        if rerun:
            st.rerun()

    
    
    def render(self):
        if not self.map_disp:
            self.refresh_map(reset_areas=True)

        c1_top, c2_top = st.columns([1, 1])
        with c1_top:
            get_event_clicked = st.button("Get Events")
        with c2_top:
            clear_prev_events_clicked = st.button("Clear All Selections")

        if get_event_clicked:
            self.refresh_map(reset_areas=False)

        if clear_prev_events_clicked:
            self.refresh_map(reset_areas=True)


        self.map_output = st_folium(
            self.map_disp, 
            use_container_width=True, 
            height=self.map_height
        )
        self.areas_current = get_selected_areas(self.map_output)
        if self.map_output and self.map_output.get('last_object_clicked') is not None:
            clicked_lat_lng = (self.map_output['last_object_clicked'].get('lat'), self.map_output['last_object_clicked'].get('lng'))
            if clicked_lat_lng in self.marker_info:
                self.clicked_marker_info = self.marker_info[clicked_lat_lng]

        if self.warning:
            st.warning(self.warning)
        
        if self.error:
            st.error(self.error)
 

class EventSelect:

    settings: SeismoLoaderSettings
    df_data_edit: pd.DataFrame = None

    def get_selected_idx(self, df_data):
        if df_data.empty:
            return []
        
        mask = df_data['is_selected']
        return df_data[mask].index.tolist()


    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings


    def sync_df_event_with_df_edit(self, df_event):
        df_event['is_selected'] = self.df_data_edit['is_selected']
        return df_event
    

    def refresh_map_selection(self, map_component):
        selected_idx = self.get_selected_idx(map_component.df_events)
        map_component.refresh_map(reset_areas=False, selected_idx=selected_idx, rerun = True)


    def render(self, map_component: EventMap):
        # Show Events in the table
        if not map_component.df_events.empty:
            cols = map_component.df_events.columns
            orig_cols   = [col for col in cols if col != 'is_selected']
            ordered_col = ['is_selected'] + orig_cols

            config = {col: {'disabled': True} for col in orig_cols}

            if 'is_selected' not in map_component.df_events.columns:
                map_component.df_events['is_selected'] = False
            config['is_selected']  = st.column_config.CheckboxColumn(
                'Select'
            )

            cc1, cc2 = st.columns([1,2])
            with cc1:
                if map_component.clicked_marker_info:
                    def handle_marker_select():
                        if st.button("Add to Selection"):
                            map_component.df_events = self.sync_df_event_with_df_edit(map_component.df_events)
                            map_component.df_events.loc[map_component.clicked_marker_info['id'], 'is_selected'] = True                                             
                            self.refresh_map_selection(map_component)

                        st.write(map_component.clicked_marker_info)

                        if map_component.df_events.loc[map_component.clicked_marker_info['id'], 'is_selected']:
                            if st.button("Unselect"):
                                map_component.df_events.loc[map_component.clicked_marker_info['id'], 'is_selected'] = False
                                # map_component.clicked_marker_info = None
                                # map_component.map_output["last_object_clicked"] = None
                                self.refresh_map_selection(map_component)
                    create_card("Selected Event from Map", handle_marker_select)
                    
                else:
                    create_card("Select a marker from map to add event to the selection", None)            
            
            def event_table_view():                
                c1, c2, c3, c4 = st.columns([1,1,1,4])
                with c1:
                    st.write(f"Total Number of Events: {len(map_component.df_events)}")
                with c2:
                    if st.button("Select All"):
                        map_component.df_events['is_selected'] = True
                with c3:
                    if st.button("Unselect All"):
                        map_component.df_events['is_selected'] = False
                with c4:
                    if st.button("Refresh Map"):
                        map_component.df_events = self.sync_df_event_with_df_edit(map_component.df_events)
                        self.refresh_map_selection(map_component)

                self.df_data_edit = st.data_editor(map_component.df_events, hide_index = True, column_config=config, column_order = ordered_col)
            with cc2:            
                create_card("List of Events", event_table_view)

        return map_component
            # selected_events = st.dataframe(df_data, key="data", on_select="rerun", selection_mode="multi-row")



class EventComponents:

    settings: SeismoLoaderSettings
    filter_menu: EventFilterMenu
    map_component: EventMap
    event_select: EventSelect

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings      = settings
        self.filter_menu   = EventFilterMenu(settings)
        self.map_component = EventMap(settings)
        self.event_select  = EventSelect(settings)

    def render(self):
        st.sidebar.header("Event Filters")
        with st.sidebar:
            self.filter_menu.render(self.map_component.refresh_map)

        self.map_component.render()
        self.map_component = self.event_select.render(self.map_component)


