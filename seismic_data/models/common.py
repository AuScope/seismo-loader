from pydantic import BaseModel


class RectangleArea(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


class CircleArea(BaseModel):
    lat   : float
    lng   : float
    min_radius: float = 0
    max_radius: float