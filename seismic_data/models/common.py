from pydantic import BaseModel
from typing import Literal

class RectangleArea(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float
    type   : Literal["station", "event"] = "event"

    @property
    def color(self) -> str:
        if self.type == "station":
            return "red"
        elif self.type == "event":
            return "green"
        return "blue"  


class CircleArea(BaseModel):
    lat   : float
    lng   : float
    min_radius: float = 0
    max_radius: float
