import streamlit as st
import pandas as pd

from seismic_data.models.common import CircleArea

from seismic_data.ui.pages.helpers.common import init_settings
from seismic_data.ui.components.events import EventBasedWorkflow

init_settings()


st.set_page_config(layout="wide")


# FIXME: This function should be moved to Station Step
def update_all_station_areas(min_radius, max_radius):
    # Convert radius values to meters
    min_radius_value = float(min_radius) * 1000
    max_radius_value = float(max_radius) * 1000

    # Update all donut areas with the new radius values
    for area in st.session_state.event_page.event.geo_constraint:
        if isinstance(area.coords, CircleArea):
            area.coords.min_radius = min_radius_value
            area.coords.max_radius = max_radius_value

# FIXME: This function should be moved to Station Step
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

def main():

    if "event_based_workflow" not in st.session_state:
        event_based_workflow                  = EventBasedWorkflow(st.session_state.event_page)
        st.session_state.event_based_workflow = event_based_workflow
    else:
        event_based_workflow                  = st.session_state.event_based_workflow
    
    event_based_workflow.render()

if __name__ == "__main__":
    main()
