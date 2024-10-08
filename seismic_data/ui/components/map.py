import folium
from folium.plugins import Draw

import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import matplotlib.cm as cm

from seismic_data.models.common import RectangleArea, CircleArea 
from seismic_data.enums.ui import Steps
# from shapely.geometry import Point
# from shapely.geometry.polygon import Polygon
# import geopandas as gpd
import streamlit as st


DEFAULT_COLOR_MARKER = 'blue'

def create_map(map_center=[-25.0000, 135.0000], areas=[]):
    """
    Default on Australia center
    """
    m = folium.Map(location=map_center, zoom_start=2, tiles='CartoDB positron', attr='Map data © OpenStreetMap contributors, CartoDB')

    Draw(
        draw_options={
            'polyline': False,  
            'rectangle': True,  
            'polygon': False,   
            'circle': True,     
            'marker': False,    
            'circlemarker': False,
        },
        edit_options={'edit': True},
        export=False
    ).add_to(m)

    folium.plugins.Fullscreen(
        position="topright",
        title="Expand me",
        title_cancel="Exit me",
        force_separate_button=True,
    ).add_to(m)

    for area in areas:
        coords = area.coords
        
        if isinstance(coords, RectangleArea):
            folium.Rectangle(
                bounds=[[coords.min_lat, coords.min_lng], [coords.max_lat, coords.max_lng]],
                color=coords.color,
                fill=True,
                fill_opacity=0.5
            ).add_to(m)

        elif isinstance(coords, CircleArea):
            if coords.min_radius == 0:
                folium.Circle(
                    location=[coords.lat, coords.lng],
                    radius=coords.max_radius,
                    color="green",  # Solid green color
                    fill=True,
                    fill_opacity=0.5
                ).add_to(m)
            else:
                # Outer circle (max_radius) with dashed lines
                folium.Circle(
                    location=[coords.lat, coords.lng],
                    radius=coords.max_radius,
                    color=coords.color,
                    fill=False,
                    dash_array='2, 4',  # Dashed lines
                    weight=2,                
                ).add_to(m)

                # Inner circle (min_radius), always with dashed lines
                folium.Circle(
                    location=[coords.lat, coords.lng],
                    radius=coords.min_radius,
                    color=coords.color,
                    fill=False,
                    dash_array='2, 4',  # Dashed lines
                    weight=2, 
                ).add_to(m)

    return m


def get_marker_color(magnitude):
    if magnitude < 1.8:
        return 'silver'
    elif 1.8 <= magnitude < 2.4:
        return 'yellow'
    elif 2.4 <= magnitude < 5:
        return 'orange'
    elif 5 <= magnitude < 7:
        return 'red'
    elif 7 <= magnitude < 8.5:
        return 'magenta'
    else:
        return 'purple'
    

def get_color_map(df, c, offset=0.0, cmap='viridis'):
    """
    offset: 0.0 <= offset <= 1   -> it is used to lower the range of colors
    """
    colormap = cm.get_cmap(cmap) 
    min_val, max_val = [df[c].min(), df[c].max()]
    norm = Normalize(vmin=min_val + offset * min_val, vmax=max_val - offset)

    return norm, colormap
    

def create_popup(index, row, cols_to_disp):
    html_disp = f"<h4>No: {index}</h4>"
    for k,v in cols_to_disp.items():
        html_disp += f"<h6>{v}: {row[k]}</h6>"

    return f"""
    <div>
        {html_disp}
    </div>
    """


def add_data_points(base_map, df, cols_to_disp, step: Steps, selected_idx=[], col_color=None):
    marker_info = {}

    for index, row in df.iterrows():
        color = DEFAULT_COLOR_MARKER if col_color is None else get_marker_color(row[col_color])

        edge_color = 'black' if index in selected_idx else color
        size = 7 if index in selected_idx else 5
        fill_opacity = 1.0 if index in selected_idx else 0.2

        popup_content = create_popup(index, row, cols_to_disp)
        popup = folium.Popup(html=popup_content, max_width=2650, min_width=200)

        latitude, longitude = row['latitude'], row['longitude']

        if step == Steps.EVENT:
            folium.CircleMarker(
                location=[latitude, longitude],
                radius=size,
                popup=popup,
                color=edge_color,
                fill=True,
                fill_color=color,
                fill_opacity=fill_opacity,
            ).add_to(base_map)

        if step == Steps.STATION:
            folium.RegularPolygonMarker(
                location=[latitude, longitude],
                number_of_sides=3,
                rotation=-90,
                radius=size,
                popup=popup,
                color=edge_color,
                fill=True,
                fill_color=color,
                fill_opacity=fill_opacity,
            ).add_to(base_map)


        # if is_original and not is_station:
        #     folium.CircleMarker(
        #         location=[latitude, longitude],
        #         radius=size,
        #         popup=popup,
        #         color=edge_color,
        #         fill=True,
        #         fill_color=color,
        #         fill_opacity=fill_opacity,
        #     ).add_to(base_map)
        # elif is_original and is_station:
        #     folium.RegularPolygonMarker(
        #         location=[latitude, longitude],
        #         number_of_sides=3,
        #         rotation=-90,
        #         radius=size,
        #         popup=popup,
        #         color=edge_color,
        #         fill=True,
        #         fill_color=color,
        #         fill_opacity=fill_opacity,
        #     ).add_to(base_map)
        # elif not is_original:
        #     folium.RegularPolygonMarker(
        #         location=[latitude, longitude],
        #         number_of_sides=5,
        #         rotation=30,
        #         radius=10,
        #         popup=popup,
        #         color=edge_color,
        #         fill=True,
        #         fill_color=color,
        #         fill_opacity=0.6
        #     ).add_to(base_map)

        marker_key = (latitude, longitude)
        if marker_key not in marker_info:
            marker_info[marker_key] = {"id": index + 1}

        for k, v in cols_to_disp.items():
            marker_info[marker_key][v] = row[k]

    return base_map, marker_info

