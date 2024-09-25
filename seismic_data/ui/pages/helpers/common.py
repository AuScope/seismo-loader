
from typing import List
import numpy as np
import streamlit as st
import os
from seismic_data.models.common import RectangleArea, CircleArea, DonutArea
from seismic_data.enums.common import GeometryType
from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint


current_directory = os.path.dirname(os.path.abspath(__file__))
target_file = os.path.join(current_directory, '../../../service/example_event.kill.cfg')
target_file = os.path.abspath(target_file)


def read_general_settings(settings: SeismoLoaderSettings):
    """
    TODO: a function that reads the latest app settings
    """
    settings.event.geo_constraint = []
    return settings

def save_general_settings(settings: SeismoLoaderSettings):
    """
    TODO: a function that saves the app settings
    """
    settings.station.geo_constraint = []
    return settings


def init_settings():
    if 'event_page' not in st.session_state:
        st.session_state.event_page = SeismoLoaderSettings()
        st.session_state.event_page = st.session_state.event_page.from_cfg_file(target_file)
        st.session_state.event_page = read_general_settings(st.session_state.event_page)

    if 'data_select_page' not in st.session_state:
        st.session_state.data_select_page = SeismoLoaderSettings()
        st.session_state.data_select_page  = st.session_state.data_select_page.from_cfg_file(target_file)
        st.session_state.data_select_page = read_general_settings(st.session_state.data_select_page)




def handle_polygon(geo) -> GeometryConstraint:
    coords_arr = np.array(geo.get("geometry").get("coordinates")[0])
    max_vals   = coords_arr.max(axis=0)
    min_vals   = coords_arr.min(axis=0)

    return GeometryConstraint(
            coords = RectangleArea(
            min_lat = min_vals[1],
            min_lng = min_vals[0],
            max_lat = max_vals[1],
            max_lng = max_vals[0],
        )
    )


def handle_circle(geo) -> GeometryConstraint:
    coords = geo.get("geometry").get("coordinates")
    radius = geo.get("properties").get("radius")

    return GeometryConstraint(
            coords = CircleArea(
            lat = coords[1],
            lng = coords[0],
            max_radius = radius
        )
    )

def handle_donut(geo) -> DonutArea:
    coords = geo.get("geometry").get("coordinates")
    min_radius = geo.get("properties").get("min_radius")
    max_radius = geo.get("properties").get("max_radius")

    return GeometryConstraint(
        coords=DonutArea(
            lat = coords[1],
            lng = coords[0],
            min_radius = min_radius,
            max_radius = max_radius
        )
    )

def get_selected_areas(map_output) -> List[RectangleArea | CircleArea | DonutArea]:
    lst_locs = []
    k = "all_drawings"
    
    if map_output.get(k):
        for geo in map_output.get(k):
            geom_type = geo.get("geometry").get('type')
            
            if geom_type == GeometryType.POLYGON:
                lst_locs.append(handle_polygon(geo))
                continue

            if geom_type == GeometryType.POINT:
                if geo.get("properties").get("min_radius") and geo.get("properties").get("max_radius"):
                    lst_locs.append(handle_donut(geo))
                else:
                    lst_locs.append(handle_circle(geo))
                continue

            raise ValueError(f"Geometry Type {geom_type} not supported!")
        
    return lst_locs