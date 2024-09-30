import folium
from folium.plugins import Draw

from seismic_data.models.common import RectangleArea, CircleArea 
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
    

def create_popup(index, row, cols_to_disp):
    html_disp = f"<h4>No: {index}</h4>"
    for k,v in cols_to_disp.items():
        html_disp += f"<h6>{v}: {row[k]}</h6>"

    return f"""
    <div>
        {html_disp}
    </div>
    """



def add_data_points(base_map, df, cols_to_disp, selected_idx=[], col_color=None):
    marker_info = {}
    
    for index, row in df.iterrows():
        if col_color is None:
            color = DEFAULT_COLOR_MARKER  
        else:
            color = get_marker_color(row[col_color])
        
        if index in selected_idx:
            radius = 10  
            color = 'darkred' 
        else:
            radius = 5 
        
        popup_content = create_popup(index, row, cols_to_disp)
        popup = folium.Popup(html=popup_content, max_width=2650, min_width=200)
        
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=radius,  
            popup=popup,
            color=color,
            fill=True,
            fill_color=color
        ).add_to(base_map)

        marker_info[(row['latitude'], row['longitude'])] = { "id": index }

        for k, v in cols_to_disp.items():
            marker_info[(row['latitude'], row['longitude'])][v] = row[k]

    return base_map, marker_info

