
from typing import List
import numpy as np
import streamlit as st
import os

import jinja2
import os

from seed_vault.models.common import RectangleArea, CircleArea
from seed_vault.enums.common import GeometryType
from seed_vault.models.config import SeismoLoaderSettings, GeometryConstraint
from seed_vault.service.seismoloader import convert_radius_to_degrees


current_directory = os.path.dirname(os.path.abspath(__file__))
target_file = os.path.join(current_directory, '../../../service/config.cfg')
target_file = os.path.abspath(target_file)


def empty_settings_geo_constraints(settings: SeismoLoaderSettings):
    """
    TODO: a function that reads the latest app settings
    """
    settings.event.geo_constraint = []
    settings.station.geo_constraint = []
    return settings


def get_app_settings(create_new: bool = True, empty_geo: bool = True):
    if "app_settings" not in st.session_state:
        settings = SeismoLoaderSettings.from_cfg_file(target_file)
        st.session_state.app_settings = settings
    else:
        if create_new:
            settings = SeismoLoaderSettings.from_cfg_file(target_file)
            st.session_state.app_settings = settings
    
    if empty_geo:
        st.session_state.app_settings = empty_settings_geo_constraints(st.session_state.app_settings)

    return st.session_state.app_settings


def set_app_settings(settings: SeismoLoaderSettings):
    st.session_state.app_settings = settings



def save_filter(settings:  SeismoLoaderSettings):
    set_app_settings(settings)
    current_directory = os.path.dirname(os.path.abspath(__file__))
    target_file = os.path.join(current_directory, '../../../service')
    target_file = os.path.abspath(target_file)
    
    template_loader = jinja2.FileSystemLoader(searchpath=target_file)  
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template("config_template.cfg")
    config_dict = get_app_settings(create_new=False, empty_geo=False).add_to_config() # settings.add_to_config()
    config_str = template.render(**config_dict)
    
    save_path = os.path.join(target_file, "config" + ".cfg")
    with open(save_path, "w") as f:
        f.write(config_str)
    
    return save_path


        
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
    # min_radius = geo.get("properties").get("min_radius")
    # max_radius = geo.get("properties").get("max_radius")
    radius = geo.get("properties").get("radius")

    return GeometryConstraint(
            coords = CircleArea(
            lat = coords[1],
            lng = coords[0],
            min_radius = 0,
            max_radius = convert_radius_to_degrees(radius)
        )
    )


def get_selected_areas(map_output) -> List[RectangleArea | CircleArea ]:
    lst_locs = []
    k = "all_drawings"
    
    if map_output.get(k):
        for geo in map_output.get(k):
            geom_type = geo.get("geometry").get('type')
            
            if geom_type == GeometryType.POLYGON:
                lst_locs.append(handle_polygon(geo))
                continue

            if geom_type == GeometryType.POINT:
                lst_locs.append(handle_circle(geo))
                continue

            raise ValueError(f"Geometry Type {geom_type} not supported!")
        
    return lst_locs