# Interactive Earthquake Map

This Streamlit application displays earthquake data for a selected date range on an interactive map. The data is fetched from the USGS Earthquake Catalog API and can be filtered by magnitude and depth.

![Screenshot of Earthquake Map](screenshot.jpg)


## Features

Select a date range to view earthquake data
Filter earthquakes by minimum and maximum magnitude
Filter earthquakes by minimum and maximum depth
Interactive map displaying earthquake locations with color-coded markers based on magnitude
Data table displaying details of the filtered earthquakes

## Installation

To run this application, you need to have Python installed. Follow the steps below to set up and run the application:

Clone the repository:
```bash
git clone https://github.com/joncutrer/earthquakemap-streamlit.git
```

Navigate to the project directory:
```bash
cd interactive-earthquake-map
```

Create a virtual environment:
```bash
python -m venv env
```

Activate the virtual environment:

On Windows:
```bash
.\env\Scripts\activate
```
On macOS and Linux:
```bash
source env/bin/activate
```
Install the required packages:
```bash
pip install -r requirements.txt
```

## Running the Application

Ensure you are in the project directory and the virtual environment is activated.

Run the Streamlit application:
```bash
streamlit run earthquakemap_streamlit/streamlit_app.py
```

Open your web browser and go to `http://localhost:8501` to view the application.

## Usage

### Select Date Range

Use the date pickers in the sidebar to select the start and end dates for the earthquake data you want to view.

### Filter Earthquakes

Use the sliders in the sidebar to set the minimum and maximum magnitude and depth for the earthquakes. The map and data table will update automatically to reflect the filtered data.

### Interactive Map

The map displays earthquake locations with color-coded markers based on magnitude:

Silver: Magnitude < 1.8
Yellow: 1.8 ≤ Magnitude < 2.4
Orange: 2.4 ≤ Magnitude < 5
Red: 5 ≤ Magnitude < 7
Magenta: 7 ≤ Magnitude < 8.5
Purple: Magnitude ≥ 8.5
Click on a marker to view details about the earthquake, including magnitude and location.

### Data Table

Below the map, a data table displays detailed information about the filtered earthquakes, including the place, magnitude, time, longitude, latitude, and depth.

## Dependencies

streamlit
pandas
requests
folium
streamlit-folium
Ensure these packages are listed in the `requirements.txt` file for easy installation.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request with your changes.

## License

This project is licensed under the MIT License. See the `LICENSE` file for more details.