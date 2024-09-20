import folium
from folium.plugins import Draw

from seismic_data.models.common import RectangleArea, CircleArea , DonutArea
from shapely.geometry import Point
from shapely.geometry.polygon import Polygon
import geopandas as gpd
import streamlit as st

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

    # Iterate over the areas to add them to the map
    for area in areas:
        if isinstance(area, RectangleArea):
            folium.Rectangle(
                bounds=[[area.min_lat, area.min_lng], [area.max_lat, area.max_lng]],
                color=area.color,
                fill=True,
                fill_opacity=0.5
            ).add_to(m)

        elif isinstance(area, CircleArea):
            folium.Circle(
                location=[area.lat, area.lng],
                radius=area.radius,
                color=area.color,
                fill=True,
                fill_opacity=0.5
            ).add_to(m)

        elif isinstance(area, DonutArea):
            folium.Circle(
                location=[area.lat, area.lng],
                radius=area.max_radius,
                color=area.color,
                fill=False,
                dash_array='2, 4',  
                weight=2,                
            ).add_to(m)

            folium.Circle(
                location=[area.lat, area.lng],
                radius=area.min_radius,
                color=area.color,
                fill=False,
                dash_array='2, 4',  
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

def add_data_points(base_map, df, col_color = 'magnitude'):
    
    marker_info = {} 
    for _, row in df.iterrows():
        color = get_marker_color(row[col_color])
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=5,
            popup=f"Latitude: {row['latitude']}<br>Longitude: {row['longitude']}<br>{col_color.capitalize()}: {row[col_color]}<br>Place: {row['place']}",
            color=color,
            fill=True,
            fill_color=color
        ).add_to(base_map)

        marker_info[(row['latitude'], row['longitude'])] = {
            "Latitude": row['latitude'],
            "Longitude": row['longitude'],
            "Magnitude": row[col_color],
            "Place": row['place']
        }

    return base_map, marker_info
