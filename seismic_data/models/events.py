from pydantic import BaseModel
from typing import Optional, List
from datetime import date, timedelta


class RectangleArea(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


class CircleArea(BaseModel):
    lat   : float
    lng   : float
    radius: float


class EventFilter(BaseModel):
    start_date   : Optional[date                            ] = date.today()
    end_date     : Optional[date                            ] = date.today() - timedelta(days=7)
    areas        : Optional[List    [RectangleArea | CircleArea]] = None
    min_magnitude: Optional[float                               ] = None
    max_magnitude: Optional[float                               ] = None
    min_depth    : Optional[float                               ] = None
    max_depth    : Optional[float                               ] = None

