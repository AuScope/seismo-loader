from pydantic import BaseModel
from typing import Literal

class RectangleArea(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float

    @property
    def color(self) -> str:
        return "#5dade2"  


class CircleArea(BaseModel):
    lat   : float
    lng   : float
    max_radius: float
    min_radius : float=0
    @property
    def color(self) -> str:
        return "#5dade2"  
