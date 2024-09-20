from pydantic import BaseModel
from typing import Literal

class RectangleArea(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float

    @property
    def color(self) -> str:
        return "green"  


class CircleArea(BaseModel):
    lat   : float
    lng   : float
    radius: float

    @property
    def color(self) -> str:
        return "green"  

class DonutArea(BaseModel):
    lat   : float
    lng   : float
    min_radius : float
    max_radius : float

    @property
    def color(self) -> str:
        return "red"  
