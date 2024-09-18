import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from copy import deepcopy

from seismic_data.ui.components.card import create_card
from seismic_data.models.events import EventFilter
from seismic_data.models.common import CircleArea, RectangleArea
from seismic_data.service.events import get_event_data, event_response_to_df
from seismic_data.ui.components.map import create_map, add_data_points
from seismic_data.ui.pages.helpers.events import event_filter_menu
from seismic_data.ui.pages.helpers.common import get_selected_areas

st.set_page_config(layout="wide")


def handle_get_events(base_map, event_filter: EventFilter):
    # GET DATA
    data = get_event_data(event_filter.model_dump())     
    components = {}
    if data:
        df = event_response_to_df(data)
        total_earthquakes = len(df)
        
        components['subheader'] = f"Showing {total_earthquakes} events"
        
        if not df.empty:
            base_map = add_data_points(base_map, df, col_color='magnitude')
            components['dataframe'] = df
        else:
            components['warning'] = "No earthquakes found for the selected magnitude and depth range."
    else:
        components['error'] = "No data available."

    components['map'] = base_map
    return components


def refresh_map(reset_areas = False):
    if "current_areas" not in st.session_state:
        st.session_state.current_areas = []

    if reset_areas:
        st.session_state.event_filter.areas = []
    else:
        st.session_state.event_filter.areas.extend(st.session_state.current_areas)
    
    
    st.session_state.event_map = {'map': create_map(areas=st.session_state.event_filter.areas)}
    if len(st.session_state.event_filter.areas) > 0:
        st.session_state.event_map = handle_get_events(st.session_state.event_map.get('map'), st.session_state.event_filter)

def update_event_filter_with_rectangles(df_rect):
    new_rectangles = [RectangleArea(**row.to_dict()) for _, row in df_rect.iterrows()]
    st.session_state.event_filter.areas = [
        area for area in st.session_state.event_filter.areas if not isinstance(area, RectangleArea)
    ] + new_rectangles

def update_event_filter_with_circles(df_circ):
    new_circles = [CircleArea(**row.to_dict()) for _, row in df_circ.iterrows()]
    st.session_state.event_filter.areas = [
        area for area in st.session_state.event_filter.areas if not isinstance(area, CircleArea)
    ] + new_circles

def right_card():
    lst_rect = []
    lst_circ = []
    for area in st.session_state.event_filter.areas:
        if isinstance(area, CircleArea):
            lst_circ.append(area.model_dump())
        if isinstance(area, RectangleArea):
            lst_rect.append(area.model_dump())
    
    st.write("Rectangle Areas")

    original_df_rect = pd.DataFrame(lst_rect, columns=RectangleArea.model_fields)
    st.session_state.df_rect = st.data_editor(original_df_rect)

    st.write("Circle Areas")
    original_df_circ = pd.DataFrame(lst_circ, columns=CircleArea.model_fields)
    st.session_state.df_circ = st.data_editor(original_df_circ)

    rect_changed = not original_df_rect.equals(st.session_state.df_rect)
    circ_changed = not original_df_circ.equals(st.session_state.df_circ)
    if rect_changed or circ_changed:
        if rect_changed:
            update_event_filter_with_rectangles(st.session_state.df_rect)
        if circ_changed:
            update_event_filter_with_circles(st.session_state.df_circ)      
        refresh_map(reset_areas=False)
        st.rerun()


    # favorite_command = edited_df.loc[edited_df["rating"].idxmax()]["command"]
    # st.markdown(f"Your favorite command is **{favorite_command}** 🎈")

    st.write(st.session_state.event_filter.model_dump())

    # st.rerun()

def main():
    # INIT event_filter object
    if 'event_filter' not in st.session_state:
        st.session_state.event_filter = EventFilter()

    # INIT side menu
    st.session_state.event_filter = event_filter_menu(st.session_state.event_filter)

    # INIT MAP  
    if 'event_map' not in st.session_state:
        st.session_state.event_map = {'map': create_map()}

    # INIT Button
    c1_top, c2_top = st.columns([1,1])
    with c1_top:
        get_event_clicked = st.button("Get Events")
    with c2_top:
        clear_prev_clicked = st.button("Clear All Selections")

    # INIT Layout
    c1_map, c2_map = st.columns([2,1])
    

    # Handle Button Clicked
    if get_event_clicked:     
        refresh_map(reset_areas=False)

    if clear_prev_clicked:
        refresh_map(reset_areas=True)

    

    with c1_map:
        output = create_card(None, st_folium, st.session_state.event_map.get('map'), use_container_width=True, height=600)
        # output = st_folium(st.session_state.event_map.get('map'), use_container_width=True, height=600)
        st.session_state.current_areas = get_selected_areas(output)
    with c2_map:
        create_card(None, right_card)
        # st.write(st.session_state.event_filter.model_dump())
        # st.write(output)
    
    if 'subheader' in st.session_state['event_map']:
        st.subheader(st.session_state['event_map']['subheader'])    
    if 'warning' in st.session_state['event_map']:
        st.warning(st.session_state['event_map']['warning'])
    if 'error' in st.session_state['event_map']:
        st.error(st.session_state['event_map']['error'])
    if 'dataframe' in st.session_state['event_map']:
        st.dataframe(st.session_state['event_map']['dataframe'])

    
    
        

if __name__ == "__main__":
    main()
