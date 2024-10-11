from pydantic import BaseModel
from seismic_data.utils.constants import AREA_COLOR

class RectangleArea(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float

    @property
    def color(self) -> str:
        return AREA_COLOR  


class CircleArea(BaseModel):
    lat   : float
    lng   : float
    max_radius: float
    min_radius : float=0
    @property
    def color(self) -> str:
        return AREA_COLOR 
