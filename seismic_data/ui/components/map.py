import folium
from folium.plugins import Draw

from seismic_data.models.common import RectangleArea, CircleArea , DonutArea
# from shapely.geometry import Point
# from shapely.geometry.polygon import Polygon
# import geopandas as gpd
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
        coords = area.coords
        if isinstance(coords, RectangleArea):
            folium.Rectangle(
                bounds=[[coords.min_lat, coords.min_lng], [coords.max_lat, coords.max_lng]],
                color=coords.color,
                fill=True,
                fill_opacity=0.5
            ).add_to(m)

        elif isinstance(coords, CircleArea):
            folium.Circle(
                location=[coords.lat, coords.lng],
                radius=coords.max_radius,
                color="green",
                fill=True,
                fill_opacity=0.5
            ).add_to(m)

        elif isinstance(coords, DonutArea):
            folium.Circle(
                location=[coords.lat, coords.lng],
                radius=coords.max_radius,
                color=coords.color,
                fill=False,
                dash_array='2, 4',  
                weight=2,                
            ).add_to(m)

            folium.Circle(
                location=[coords.lat, coords.lng],
                radius=coords.min_radius,
                color=coords.color,
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
    

def create_popup(index, row, cols_to_disp):
    html_disp = f"<h4>No: {index}</h4>"
    for k,v in cols_to_disp.items():
        html_disp += f"<h6>{v}: {row[k]}</h6>"

    return f"""
    <div>
        {html_disp}
    </div>
    """


def add_data_points(base_map, df, cols_to_disp, col_color = 'magnitude'):
    marker_info = {} 
    for index, row in df.iterrows():
        color = get_marker_color(row[col_color])
        popup_content = create_popup(index, row, cols_to_disp)
        popup = folium.Popup(html=popup_content, max_width=2650, min_width=200)
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=5,
            popup=popup,
            color=color,
            fill=True,
            fill_color=color
        ).add_to(base_map)

        marker_info[(row['latitude'], row['longitude'])] = { "id": index }

        for k,v in cols_to_disp.items():
            marker_info[(row['latitude'], row['longitude'])][v] = row[k]

    return base_map, marker_info
