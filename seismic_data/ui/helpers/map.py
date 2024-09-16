import folium
from folium.plugins import Draw

def create_map(map_center=[-25.0000, 135.0000]):
    """
    Default on Australia center
    """
    m = folium.Map(location=map_center, zoom_start=2, tiles='CartoDB positron', attr='Map data © OpenStreetMap contributors, CartoDB')
    
    # m = folium.Map(location=map_center, zoom_start=2)

    # folium.TileLayer(
    #     tiles='Stamen Toner',
    #     attr='Map data © OpenStreetMap contributors, Stamen Design'
    # ).add_to(m)


    # folium.TileLayer(
    #     tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',  # This is the default OSM tile, replace with an appropriate English-labeled tile if needed
    #     attr='Map data © OpenStreetMap contributors'
    # ).add_to(m)

    Draw(
        draw_options={
            'polyline': False,  # Users can draw lines
            'rectangle': True,  # Users can draw rectangles (boxes)
            'polygon': False,    # Users can draw polygons
            'circle': True,    # Users can draw circles
            'marker': False,     # Users can place markers
            'circlemarker': False,
        },
        edit_options={'edit': False},
        export=False
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
    
    for _, row in df.iterrows():
        color = get_marker_color(row[col_color])
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=5,
            popup=f"{col_color.capitalize()}: {row[col_color]}, Place: {row['place']}",
            color=color,
            fill=True,
            fill_color=color
        ).add_to(base_map)
    
    return base_map
