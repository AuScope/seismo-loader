from enum import Enum


class DescribedEnum(Enum):
    def __new__(cls, value, description):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.description = description
        return obj

    def __str__(self):
        return f"{self.name} ({self.value}): {self.description}"

class GeometryType(str, Enum):
    POLYGON = 'Polygon'
    POINT   = 'Point'