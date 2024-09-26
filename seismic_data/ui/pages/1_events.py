import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from copy import deepcopy

from seismic_data.ui.components.card import create_card
from seismic_data.enums.config import GeoConstraintType
from seismic_data.models.config import SeismoLoaderSettings, GeometryConstraint
from seismic_data.models.common import CircleArea, RectangleArea
from seismic_data.service.events import get_event_data, event_response_to_df
from seismic_data.ui.components.map import create_map, add_data_points
from seismic_data.ui.pages.helpers.common import get_selected_areas

from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.event_filter import event_filter_menu
from seismic_data.ui.components.station_filter import station_filter_menu

init_settings()


st.set_page_config(layout="wide")


def handle_get_events(base_map, settings: SeismoLoaderSettings):
    # GET DATA
    data = get_event_data(settings.model_dump_json())
    components = {}
    if data:
        # Convert records to a DataFrame (optional)
        df = event_response_to_df(data)
        # df = event_response_to_df(data)
        total_earthquakes = len(df)
        
        components['subheader'] = f"Showing {total_earthquakes} events"
        
        if not df.empty:
            base_map, marker_info = add_data_points(base_map, df, col_color='magnitude')
            components['dataframe'] = df
            components['marker_info'] = marker_info  

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
        st.session_state.event_page.event.geo_constraint = []
    else:
        st.session_state.event_page.event.geo_constraint.extend(st.session_state.current_areas)
    
    st.session_state.event_map = {'map': create_map(areas=st.session_state.event_page.event.geo_constraint)}
    if len(st.session_state.event_page.event.geo_constraint) > 0:
        result = handle_get_events(st.session_state.event_map.get('map'), st.session_state.event_page)
        st.session_state.event_map = result
        st.session_state.marker_info = result.get('marker_info', {}) 
      

def update_event_filter_geometry(df, geo_type: GeoConstraintType):
    add_geo = []
    for _, row in df.iterrows():
        coords = row.to_dict()
        if geo_type == GeoConstraintType.BOUNDING:
            add_geo.append(GeometryConstraint(coords=RectangleArea(**coords)))
        if geo_type == GeoConstraintType.CIRCLE:
            add_geo.append(GeometryConstraint(coords=CircleArea(**coords)))

    new_geo = []
    for area in st.session_state.event_page.event.geo_constraint:
        if area.geo_type != geo_type:
            new_geo.append(area)
    st.session_state.event_page.event.geo_constraint.extend(new_geo)
        
def update_event_filter_with_rectangles(df_rect):
    new_geo = [GeometryConstraint(coords=RectangleArea(**row.to_dict())) for _, row in df_rect.iterrows()]
    st.session_state.event_page.event.geo_constraint = [
        area for area in st.session_state.event_page.event.geo_constraint 
        if not (isinstance(area.coords, RectangleArea) )
    ] + new_geo


def update_event_filter_with_circles(df_circ):
    new_circles = [CircleArea(**row.to_dict()) for _, row in df_circ.iterrows()]
    st.session_state.event_page.event.geo_constraint = [
        area for area in st.session_state.event_page.event.geo_constraint 
        if not (isinstance(area.coords, CircleArea) )
    ] + new_circles

def update_event_filter_with_donuts(df_donut):
    new_donuts = [CircleArea(**row.to_dict()) for _, row in df_donut.iterrows()]

    st.session_state.event_page.event.geo_constraint = [
        area for area in st.session_state.event_page.event.geo_constraint 
        if not isinstance(area.coords, CircleArea)
    ] + new_donuts



def update_circle_areas():
    lst_circ = [area.coords.model_dump() for area in st.session_state.event_page.event.geo_constraint
                if area.geo_type == GeoConstraintType.CIRCLE ]

    if lst_circ:
        st.write(f"Circle Areas")
        original_df_circ = pd.DataFrame(lst_circ, columns=CircleArea.model_fields)
        st.session_state.df_circ = st.data_editor(original_df_circ, key=f"circ_area")

        circ_changed = not original_df_circ.equals(st.session_state.df_circ)

        if circ_changed:
            update_event_filter_geometry(st.session_state.df_circ, GeoConstraintType.CIRCLE)
            refresh_map(reset_areas=False)
            st.rerun()

def update_rectangle_areas():
    lst_rect = [area.coords.model_dump() for area in st.session_state.event_page.event.geo_constraint
                if isinstance(area.coords, RectangleArea) ]

    if lst_rect:
        st.write(f"Rectangle Areas")
        original_df_rect = pd.DataFrame(lst_rect, columns=RectangleArea.model_fields)
        st.session_state.df_rect = st.data_editor(original_df_rect, key=f"rect_area")

        rect_changed = not original_df_rect.equals(st.session_state.df_rect)

        if rect_changed:
            update_event_filter_geometry(st.session_state.df_rect, GeoConstraintType.BOUNDING)
            refresh_map(reset_areas=False)
            st.rerun()

def update_donut_areas():
    # Display and allow editing of all donut areas
    lst_donut = [area.coords.model_dump() for area in st.session_state.event_page.event.geo_constraint if isinstance(area.coords, CircleArea)]

    if lst_donut:
        st.write("Station Areas from selected events")
        original_df_donut = pd.DataFrame(lst_donut, columns=CircleArea.model_fields)

        st.session_state.df_donut = st.data_editor(original_df_donut, key="donut_area")

        donut_changed = not original_df_donut.equals(st.session_state.df_donut)

        if donut_changed:
            update_event_filter_geometry(st.session_state.df_donut, GeoConstraintType.CIRCLE)
            refresh_map(reset_areas=False)
            st.rerun()

def update_all_station_areas(min_radius, max_radius):
    # Convert radius values to meters
    min_radius_value = float(min_radius) * 1000
    max_radius_value = float(max_radius) * 1000

    # Update all donut areas with the new radius values
    for area in st.session_state.event_page.event.geo_constraint:
        if isinstance(area.coords, CircleArea):
            area.coords.min_radius = min_radius_value
            area.coords.max_radius = max_radius_value

def station_card():
    # Text input for global radius values
    min_radius = st.text_input("Enter the minimum radius for all areas (km)", value="0")
    max_radius = st.text_input("Enter the maximum radius for all areas (km)", value="1000")

    # Update the map when radius values change
    if 'prev_min_radius' not in st.session_state:
        st.session_state.prev_min_radius = min_radius
    if 'prev_max_radius' not in st.session_state:
        st.session_state.prev_max_radius = max_radius

    if min_radius != st.session_state.prev_min_radius or max_radius != st.session_state.prev_max_radius:
        update_all_station_areas(min_radius, max_radius)
        refresh_map(reset_areas=False)
        st.session_state.prev_min_radius = min_radius
        st.session_state.prev_max_radius = max_radius
        st.rerun()

    # Check if a marker was clicked
    if 'clicked_marker_info' in st.session_state:
        st.write("Latest Selected Event:")

        # Display the selected marker information in a table with background color
        marker_info = st.session_state.clicked_marker_info
        df_marker = pd.DataFrame([marker_info])

        # Custom CSS to style the header of the table
        st.markdown(
            """
            <style>
            thead tr {
                background-color: #dff0d8 !important; /* Light green background */
                color: black !important;
            }
            th {
                text-align: left !important;
            }
            div[data-testid="stTable"] {
                margin-top: -15px !important;  /* Reduce space between table and button */
                margin-bottom: -15px !important;
             }
            </style>
            </style>
            """, 
            unsafe_allow_html=True
        )

        # Render the table with the applied style
        st.markdown('<div class="highlighted-table">', unsafe_allow_html=True)
        st.table(df_marker)
        st.markdown('</div>', unsafe_allow_html=True)

        # Add station area button
        if st.button("Add station area"):
            try:
                # Convert radius values to meters
                min_radius_value = float(min_radius) * 1000
                max_radius_value = float(max_radius) * 1000

                if min_radius_value >= max_radius_value:
                    st.error("Minimum radius should be less than the maximum radius.")
                    return

                # Get the latitude and longitude of the clicked marker
                lat = marker_info["Latitude"]
                lng = marker_info["Longitude"]

                # Add a new donut-shaped area
                new_donut = CircleArea(lat=lat, lng=lng, min_radius=min_radius_value, max_radius=max_radius_value)
                st.session_state.event_page.event.geo_constraint.append(new_donut)

                refresh_map(reset_areas=False)
                del st.session_state.clicked_marker_info

                st.success(f"Donut-shaped area added with min radius {min_radius_value / 1000} km and max radius {max_radius_value / 1000} km at ({lat}, {lng})")
                st.rerun()
            except ValueError:
                st.error("Please enter valid numbers for the radii.")

    # Call to update_donut_areas for managing the areas in the editor
    update_donut_areas()

def right_card():
    
    update_rectangle_areas()
    update_circle_areas()

    # Display the current event filter state
    st.write(st.session_state.event_page.model_dump())


# Initialize session state for stages if not already done
if 'stage' not in st.session_state:
    st.session_state.stage = 1  # Start at stage 1

# Helper function to advance stages
def next_stage():
    st.session_state.stage += 1
    st.rerun()

# Helper function to go back stages
def previous_stage():
    st.session_state.stage -= 1
    st.rerun()


def main():

    # Stage 1: Event options
    if st.session_state.stage == 1:
        st.write("Stage 1: Event options")
        
        # Button to go to the next stage
        if st.button("Next"):
            next_stage()

        # Place Event options in sidebar
        st.sidebar.header("Event options")
        with st.sidebar:
            st.session_state.event_page = event_filter_menu(st.session_state.event_page, key='event_page_event')

        # INIT MAP  
        if 'event_map' not in st.session_state:
            st.session_state.event_map = {'map': create_map()}

        # INIT Button
        c1_top, c2_top = st.columns([1, 1])
        with c1_top:
            get_event_clicked = st.button("Get Events")
        with c2_top:
            clear_prev_events_clicked = st.button("Clear All Selections")

        # INIT Layout
        c1_map, c2_map = st.columns([2, 1])

        # Handle Button Clicked
        if get_event_clicked:
            refresh_map(reset_areas=False)

        if clear_prev_events_clicked:
            refresh_map(reset_areas=True)

        with c1_map:
            output = create_card(None, st_folium, st.session_state.event_map.get('map'), use_container_width=True, height=600)
            st.session_state.current_areas = get_selected_areas(output)

            if output and output.get('last_object_clicked') is not None:
                clicked_lat_lng = (output['last_object_clicked'].get('lat'), output['last_object_clicked'].get('lng'))
                if clicked_lat_lng in st.session_state.marker_info:
                    st.session_state.clicked_marker_info = st.session_state.marker_info[clicked_lat_lng]

        with c2_map:
            create_card(None, right_card)

    # Stage 2: Station options
    elif st.session_state.stage == 2:
        st.write("Stage 2: Station options")

        # Buttons to navigate stages
        c1_nav, c2_nav = st.columns([1, 1])
        with c1_nav:
            if st.button("Previous"):
                previous_stage()
        with c2_nav:
            if st.button("Next"):
                next_stage()

        # Place Station options in sidebar
        st.sidebar.header("Station options")
        with st.sidebar:
            st.session_state.event_page = create_card(
                None, 
                station_filter_menu, 
                st.session_state.event_page, 
                key='event_page_station'
            )
            create_card(None, station_card)

        # INIT MAP  
        if 'station_map' not in st.session_state:
            st.session_state.station_map = {'map': create_map()}

        # INIT Button
        c1_top, c2_top = st.columns([1, 1])
        with c1_top:
            get_station_clicked = st.button("Get station")
        with c2_top:
            clear_prev_stations_clicked = st.button("Clear All Selections")

        # INIT Layout
        c1_map, c2_map = st.columns([2, 1])

        # Handle Button Clicked
        if get_station_clicked:
            refresh_map(reset_areas=False)

        if clear_prev_stations_clicked:
            refresh_map(reset_areas=True)

        with c1_map:
            output = create_card(None, st_folium, st.session_state.event_map.get('map'), use_container_width=True, height=600)
            st.session_state.current_areas = get_selected_areas(output)

            if output and output.get('last_object_clicked') is not None:
                clicked_lat_lng = (output['last_object_clicked'].get('lat'), output['last_object_clicked'].get('lng'))
                if clicked_lat_lng in st.session_state.marker_info:
                    st.session_state.clicked_marker_info = st.session_state.marker_info[clicked_lat_lng]

    # Stage 3: Review & Confirmation
    elif st.session_state.stage == 3:
        st.write("Stage 3: Review & Confirmation")
        st.write("Here you can review all the selections and confirm the process.")

        # Navigation buttons
        c1_nav, c2_nav = st.columns([1, 1])
        with c1_nav:
            if st.button("Previous"):
                previous_stage()
        with c2_nav:
            if st.button("Finish"):
                st.write("Process finished!")

    # Check for additional session state variables to display
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
