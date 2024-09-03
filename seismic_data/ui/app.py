import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta



st.set_page_config(
    page_title="Interactive Earthquake Map",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)



# Function to fetch earthquake data for a specific date range and filters
@st.cache_data
def get_earthquake_data(start_date, end_date, min_magnitude, max_magnitude, min_depth, max_depth):
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query"
        "?format=geojson"
        f"&starttime={start_date}"
        f"&endtime={end_date}"
        f"&minmagnitude={min_magnitude}"
        f"&maxmagnitude={max_magnitude}"
        f"&mindepth={min_depth}"
        f"&maxdepth={max_depth}"
    )
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        st.error(f"Failed to fetch data: {response.status_code}")
        return None

# Convert the earthquake data to a pandas DataFrame
def earthquake_data_to_df(data):
    features = data['features']
    records = []
    for feature in features:
        properties = feature['properties']
        geometry = feature['geometry']['coordinates']
        record = {
            'place': properties['place'],
            'magnitude': properties['mag'],
            'time': pd.to_datetime(properties['time'], unit='ms'),
            'longitude': geometry[0],
            'latitude': geometry[1],
            'depth': geometry[2]
        }
        records.append(record)
    return pd.DataFrame(records)

# Get color based on magnitude
def get_marker_color(magnitude):
    if magnitude < 1.8:
        return 'silver'
    elif 1.8 <= magnitude < 2.4:
        return 'yellow'
    elif 2.4 <= magnitude < 5:
        return 'orange'
    elif 5 <= magnitude < 7:
        return 'red'
    elif 7 <= magnitude < 8.5:
        return 'magenta'
    else:
        return 'purple'

# Plot the earthquakes on an interactive map
def plot_earthquakes_on_map(df):
    map_center = [df['latitude'].mean(), df['longitude'].mean()]
    m = folium.Map(location=map_center, zoom_start=2)
    
    for _, row in df.iterrows():
        color = get_marker_color(row['magnitude'])
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=5,
            popup=f"Magnitude: {row['magnitude']}, Place: {row['place']}",
            color=color,
            fill=True,
            fill_color=color
        ).add_to(m)
    
    return m

# Streamlit app
def main():
    st.title("Earthquake Data")
    st.markdown("This app displays earthquake data for a selected date range on an interactive map.")
    
    # Sidebar date input
    st.sidebar.header("Select Date Range")
    start_date = st.sidebar.date_input("Start Date", datetime.now() - timedelta(days=1))
    end_date = st.sidebar.date_input("End Date", datetime.now())
    
    if start_date > end_date:
        st.sidebar.error("Error: End Date must fall after Start Date.")
    
    st.sidebar.header("Filter Earthquakes")
    min_magnitude = st.sidebar.slider("Min Magnitude", min_value=0.0, max_value=10.0, value=2.4, step=0.1)
    max_magnitude = st.sidebar.slider("Max Magnitude", min_value=0.0, max_value=10.0, value=10.0, step=0.1)
    min_depth = st.sidebar.slider("Min Depth (km)", min_value=0.0, max_value=250.0, value=0.0, step=1.0)
    max_depth = st.sidebar.slider("Max Depth (km)", min_value=0.0, max_value=250.0, value=200.0, step=1.0)
    
    data = get_earthquake_data(start_date, end_date, min_magnitude, max_magnitude, min_depth, max_depth)
    
    if data:
        df = earthquake_data_to_df(data)
        total_earthquakes = len(df)
        
        filtered_df = df
        num_filtered_earthquakes = len(filtered_df)
        
        st.subheader(f"Showing {num_filtered_earthquakes} of {total_earthquakes} earthquakes")
        
        if not filtered_df.empty:
            st_map = plot_earthquakes_on_map(filtered_df)
            st_folium(st_map, width=1400, height=700)
        else:
            st.warning("No earthquakes found for the selected magnitude and depth range.")
        
        st.dataframe(filtered_df)
    else:
        st.error("No data available.")

if __name__ == "__main__":
    main()
