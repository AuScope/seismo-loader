import streamlit as st
import pandas as pd

from seismic_data.models.common import CircleArea

from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.base import BaseComponent
from seismic_data.enums.ui import Steps

init_settings()
st.set_page_config(layout="wide")


def main():

    if "test_station_based" not in st.session_state:
        station_based_workflow                  = BaseComponent(st.session_state.station_page, Steps.STATION)
        st.session_state.test_station_based = station_based_workflow
    else:
        station_based_workflow                  = st.session_state.test_station_based
    
    station_based_workflow.render()

if __name__ == "__main__":
    main()