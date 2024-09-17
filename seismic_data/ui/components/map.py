import folium
from folium import plugins
from folium.plugins import Draw
from folium.utilities import JsCode

from seismic_data.models.common import RectangleArea, CircleArea

# def create_map(map_center=[-25.0000, 135.0000], areas=[]):
#     """
#     Default on Australia center
#     """
#     m = folium.Map(location=map_center, zoom_start=2, tiles='CartoDB positron', attr='Map data © OpenStreetMap contributors, CartoDB')

#     draw = Draw(
#         draw_options={
#             'polyline': False,  
#             'rectangle': {'repeatMode': True},  
#             'polygon': False,   
#             'circle': True,     
#             'marker': False,    
#             'circlemarker': False,
#         },
#         edit_options={'edit': True},
#         export=False
#     )
#     draw.add_to(m)

#     folium.plugins.Fullscreen(
#         position="topright",
#         title="Expand me",
#         title_cancel="Exit me",
#         force_separate_button=True,
#     ).add_to(m)

#     return m

    

#     # script = f"""
#     # <script>
#     # document.addEventListener("DOMContentLoaded", function() {{
#     #     var drawnItems = new L.featureGroup().addTo({m.get_name()});
#     #     new L.Control.Draw({{
#     #         edit: {{
#     #             featureGroup: drawnItems,
#     #             remove: false
#     #         }},
#     #         draw: {{
#     #             polyline: false,
#     #             rectangle: true,
#     #             circle: true,
#     #             polygon: true,
#     #             marker: false,
#     #             circlemarker: false
#     #         }}
#     #     }}).addTo({m.get_name()});

#     #     {m.get_name()}.on(L.Draw.Event.CREATED, function (e) {{
#     #         var type = e.layerType,
#     #             layer = e.layer;
#     #         drawnItems.clearLayers();  // Remove previous layers
#     #         drawnItems.addLayer(layer); // Add new layer
#     #     }});
#     # }});
#     # </script>
#     # """

#     # highlight = JsCode(
#     #     """
#     #     function highlight(e) {
#     #         e.target.original_color = e.layer.options.color;
#     #         e.target.setStyle({ color: "green" });
#     #     }
#     #     """
#     # )

#     # reset = JsCode(
#     #     """
#     #     function reset(e) {
#     #         e.target.setStyle({ color: e.target.original_color });
#     #     }
#     #     """
#     # )

#     # m.add_child(folium.elements.EventHandler("mouseover", highlight))
#     # m.add_child(folium.elements.EventHandler("mouseout", reset))
#     # # m.get_root().html.add_child(folium.Element(script))
#     # m.get_root().script.add_child(folium.Element(script))
#     # return m



def create_map(map_center=[-25.0000, 135.0000], areas = []):
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
        if isinstance(area, RectangleArea):
            folium.Rectangle(
                bounds=[[area.min_lat, area.min_lng], [area.max_lat, area.max_lng]],
                color="green",
                fill=True,
                fill_opacity=0.5
            ).add_to(m)

        if isinstance(area, CircleArea):
            folium.Circle(
                location=[area.lat, area.lng],
                radius=area.radius,
                color="green",
                fill=True,
                fill_opacity=0.5
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
