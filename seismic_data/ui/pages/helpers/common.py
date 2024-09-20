
from typing import List
import numpy as np
from seismic_data.models.common import RectangleArea, CircleArea, DonutArea
from seismic_data.enums.common import GeometryType


def handle_polygon(geo) -> RectangleArea:
    coords_arr = np.array(geo.get("geometry").get("coordinates")[0])
    max_vals   = coords_arr.max(axis=0)
    min_vals   = coords_arr.min(axis=0)

    return RectangleArea(
        min_lat = min_vals[1],
        min_lng = min_vals[0],
        max_lat = max_vals[1],
        max_lng = max_vals[0],
    )


def handle_circle(geo) -> CircleArea:
    coords = geo.get("geometry").get("coordinates")
    radius = geo.get("properties").get("radius")

    return CircleArea(
        lat = coords[1],
        lng = coords[0],
        max_radius = radius
    )

def handle_donut(geo) -> DonutArea:
    coords = geo.get("geometry").get("coordinates")
    min_radius = geo.get("properties").get("min_radius")
    max_radius = geo.get("properties").get("max_radius")

    return DonutArea(
        lat = coords[1],
        lng = coords[0],
        min_radius = min_radius,
        max_radius = max_radius
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