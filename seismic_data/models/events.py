from pydantic import BaseModel
from typing import Optional, List
from datetime import date, timedelta

from .common import RectangleArea, CircleArea


class EventFilter(BaseModel):
    start_date   : Optional[date                            ] = date.today()
    end_date     : Optional[date                            ] = date.today() - timedelta(days=7)
    areas        : Optional[List    [RectangleArea | CircleArea]] = []
    min_magnitude: Optional[float                               ] = None
    max_magnitude: Optional[float                               ] = None
    min_depth    : Optional[float                               ] = None
    max_depth    : Optional[float                               ] = None

