from enum import Enum


class Networks(str, Enum):
    NTWK_DU = "DU"
    NTWK_1K = "1K"


class Stations(str, Enum):
    DU_TPSO = "DU.TPSO"
    DU_BAD1 = "DU.BAD1"
    DU_BAD3 = "DU.BAD3"
    TPSO    = "TPSO"


class Channels(str, Enum):
    CH = "CH"
    HH = "HH"   
    BH = "BH"   
    EH = "EH"   
    HN = "HN"   
    EN = "EN"   
    SH = "SH"   
    LH = "LH"   
    Q_HZ = "?HZ"
    Q_HN = "?HN"
    Q_HE = "?HE"

class Locations(str, Enum):
    LOC_10 = "10"
    LOC_00 = "00"
    LOC_20 = "20"
    LOC_30 = "30"


