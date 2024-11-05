import re
from typing import List, Dict
from obspy import UTCDateTime
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_event
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from obspy.geodetics import degrees2kilometers
from obspy.geodetics.base import locations2degrees

### debug missing EARTHSCOPE key in URL_MAPPINGS.. it should be there for 1.4.1!!
from obspy import __version__ as obspyversion
from obspy.clients.fdsn.header import URL_MAPPINGS
if 'EARTHSCOPE' not in URL_MAPPINGS.keys():
    print("SOMETHING IS WRONG::: 'EARTHSCOPE' not in URL_MAPPINGS for obspy version ", obspyversion)
    URL_MAPPINGS.update({'EARTHSCOPE':'http://service.iris.edu'})


class WaveformFilterMenu:
    settings: SeismoLoaderSettings
    network_filter: str
    station_filter: str
    channel_filter: str
    available_channels: List[str]
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.network_filter = "All networks"
        self.station_filter = "All stations"
        self.channel_filter = "All channels"
        self.available_channels = ["All channels"]
        if self.settings.event.before_p_sec is None:
            self.settings.event.before_p_sec = 20  # Default to 20 seconds before
        if self.settings.event.after_p_sec is None:
            self.settings.event.after_p_sec = 160  # Default to 160 seconds after
    def update_available_channels(self, waveforms):
        if not waveforms:
            self.available_channels = ["All channels"]
            return
            
        channels = set()
        for waveform in waveforms:
            if waveform.get('Channel'):  
                channels.add(waveform['Channel'])
        self.available_channels = ["All channels"] + sorted(list(channels))
        
        # Reset channel filter if current selection is invalid
        if self.channel_filter not in self.available_channels:
            self.channel_filter = "All channels"
    
    def render(self, waveforms=None):
        st.sidebar.header("Waveform Filters")

        # Update available channels if waveforms are provided
        if waveforms is not None:
            self.update_available_channels(waveforms)

        # Network filter
        networks = ["All networks"] + list(set([inv.code for inv in self.settings.station.selected_invs]))
        self.network_filter = st.sidebar.selectbox(
            "Network:",
            networks,
            index=networks.index(self.network_filter)
        )
        
        # Station filter
        stations = ["All stations"]
        for inv in self.settings.station.selected_invs:
            stations.extend([sta.code for sta in inv])
        stations = list(set(stations))
        stations.remove("All stations")
        stations.insert(0, "All stations")  
        self.station_filter = st.sidebar.selectbox(
            "Station:",
            stations,
            index=stations.index(self.station_filter)
        )

        # Channel filter 
        selected_channel = st.sidebar.selectbox(
            "Channel:",
            options=self.available_channels,
            index=self.available_channels.index(self.channel_filter)
        )
        self.channel_filter = selected_channel 
        
        # Time window around P arrival
        st.sidebar.subheader("Time Window")
        self.settings.event.before_p_sec = st.sidebar.number_input(
            "Start (secs before P arrival):", 
            value=20
        )
        self.settings.event.after_p_sec = st.sidebar.number_input(
            "End (secs after P arrival):", 
            value=100
        )

class WaveformDisplay:
    settings: SeismoLoaderSettings
    waveforms: List[Dict] = []
    ttmodel: TauPyModel = None
    prediction_data: Dict[str, any] = {}
    filter_menu: WaveformFilterMenu
    
    def __init__(self, settings: SeismoLoaderSettings, filter_menu: WaveformFilterMenu):
        self.settings = settings
        self.filter_menu = filter_menu
        self.client = Client(self.settings.waveform.client.value)
        self.ttmodel = TauPyModel("iasp91")
        self.waveforms = []
        
    def apply_filters(self, df):
        filtered_df = df.copy()
        if self.filter_menu.network_filter != "All networks":
            filtered_df = filtered_df[filtered_df["Network"] == self.filter_menu.network_filter]
        if self.filter_menu.station_filter != "All stations":
            filtered_df = filtered_df[filtered_df["Station"] == self.filter_menu.station_filter]
        if self.filter_menu.channel_filter != "All channels":
            filtered_df = filtered_df[filtered_df["Channel"] == self.filter_menu.channel_filter]
        return filtered_df
    
    def retrieve_waveforms(self):
        if (
            not self.settings.event.selected_catalogs
            or not self.settings.station.selected_invs
        ):
            st.warning(
                "Please select events and stations before downloading waveforms."
            )
            return
        self.waveforms = run_event(self.settings)
        # Filter waveforms
        filtered_waveforms = [
            ts
            for ts in self.waveforms
            if re.match(r"^[A-Z]H[A-Z]?$", ts["Channel"])
            and ts["Data"] is not None
            and not ts["Data"].empty
        ]
        self.waveforms = filtered_waveforms
        if self.waveforms:
            self.filter_menu.update_available_channels(self.waveforms)
            st.success(f"Successfully retrieved {len(self.waveforms)} waveforms.")
        else:
            st.warning("No waveforms retrieved. Please check your selection criteria.")

    def display_waveform_data(self):
        if not self.waveforms:
            st.info(
                "No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms."
            )
            return

        # Update filter menu channels before displaying
        self.filter_menu.update_available_channels(self.waveforms)
        
        all_waveforms = pd.DataFrame(self.waveforms)
        filtered_waveforms = self.apply_filters(all_waveforms)
        
        if filtered_waveforms.empty:
            st.warning("No waveforms match the current filter criteria.")
            return
        # Calculate distances for each station
        distances = {}
        if self.settings.event.selected_catalogs:
            event = self.settings.event.selected_catalogs[0]
            event_lat = event.origins[0].latitude
            event_lon = event.origins[0].longitude
            for network in self.settings.station.selected_invs:
                for station in network:
                    key = f"{network.code}.{station.code}"
                    dist_deg = locations2degrees(
                        event_lat, event_lon,
                        station.latitude, station.longitude
                    )
                    dist_km = degrees2kilometers(dist_deg)
                    distances[key] = {
                        'deg': round(dist_deg, 2),
                        'km': round(dist_km, 2)
                    }
        # Pagination (moved to sidebar)
        waveforms_per_page = 5
        num_pages = (len(filtered_waveforms) - 1) // waveforms_per_page + 1
        page = st.sidebar.selectbox(
            "Page Navigation", 
            range(1, num_pages + 1), 
            key="sidebar_pagination"
        ) - 1

        start_idx = page * waveforms_per_page
        end_idx = min((page + 1) * waveforms_per_page, len(filtered_waveforms))
        page_waveforms = filtered_waveforms.iloc[start_idx:end_idx]

        fig = make_subplots(
            rows=len(page_waveforms),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.12,
            subplot_titles=[
            self.create_subplot_title(w, distances)
                for w in page_waveforms.to_dict("records")
            ],
        )

        for i, waveform in enumerate(page_waveforms.to_dict("records"), 1):
            df = waveform["Data"]
            if df.empty:
                st.warning(
                    f"No data available for {waveform['Network']}.{waveform['Station']}.{waveform['Location']}.{waveform['Channel']}"
                )
                continue

            # Ensure the data is sorted by time
            df = df.sort_values("time")

            # Create the waveform trace
            trace = go.Scatter(
                x=df["time"],
                y=df["amplitude"],
                mode="lines",
                name=f"{waveform['Network']}.{waveform['Station']}.{waveform['Location']}.{waveform['Channel']}",
                hovertemplate="Time: %{x}<br>Amplitude: %{y:.2f}<extra></extra>",
                showlegend=False
            )
            
            # Add P arrival time marker if available and within data range
            if 'P_Arrival' in waveform and waveform['P_Arrival'] is not None:
                p_arrival_time = UTCDateTime(waveform['P_Arrival'])
                # Create window around P arrival using settings
                window_start = p_arrival_time - self.settings.event.before_p_sec
                window_end = p_arrival_time + self.settings.event.after_p_sec
                
                # Filter data to our window
                df = df[
                    (df['time'] >= window_start.datetime) & 
                    (df['time'] <= window_end.datetime)
                ]
            # Create the waveform trace
            trace = go.Scatter(
                x=df["time"],
                y=df["amplitude"],
                mode="lines",
                name=f"{waveform['Network']}.{waveform['Station']}.{waveform['Location']}.{waveform['Channel']}",
                hovertemplate="Time: %{x}<br>Amplitude: %{y:.2f}<extra></extra>",
                showlegend=False
            )

            # Add P arrival time marker
            if 'P_Arrival' in waveform and waveform['P_Arrival'] is not None:
                p_arrival_time = UTCDateTime(waveform['P_Arrival'])
                
                # Get y-axis range for this specific subplot
                y_min = df['amplitude'].min()
                y_max = df['amplitude'].max()
                margin = (y_max - y_min) * 0.1
                
                p_line = go.Scatter(
                    x=[p_arrival_time.datetime, p_arrival_time.datetime],
                    y=[y_min - margin, y_max + margin],
                    mode='lines',
                    line=dict(color='red', width=1, dash='dash'),
                    showlegend=False
                )
                
                fig.add_trace(trace, row=i, col=1)
                fig.add_trace(p_line, row=i, col=1)
                
                # Update y-axis range for this subplot
                fig.update_yaxes(
                    range=[y_min - margin, y_max + margin],
                    row=i,
                    col=1
                )
            else:
                fig.add_trace(trace, row=i, col=1)

        fig.update_layout(
            height=300 * len(page_waveforms),
            title_text=f"Seismic Waveforms (Page {page + 1} of {num_pages})",
            plot_bgcolor="white",
            margin=dict(l=100, r=100, t=300, b=100),
            legend=dict(
                yanchor="top",
                y=1.02,
                xanchor="left",
                x=1.05,
                orientation="h"
            ),
            showlegend=True,
        )
        
        for i in range(1, len(page_waveforms) + 1):
            fig.update_xaxes(
                title_text="Time (UTC)", 
                type="date",
                tickformat="%H:%M:%S",
                gridcolor="lightgrey",
                row=i,
                col=1,
                showticklabels=True,  
                nticks=8  
            )
        for annotation in fig.layout.annotations:
            annotation.update(y=annotation.y + 0.02)
        st.plotly_chart(fig, use_container_width=True)
        
    def create_subplot_title(self, waveform, distances):
        station_key = f"{waveform['Network']}.{waveform['Station']}"
        base_title = f"{waveform['Network']}.{waveform['Station']}.{waveform['Location']}.{waveform['Channel']}"
        
        if station_key in distances:
            dist = distances[station_key]
            p_arrival = waveform.get('P_Arrival')
            p_time = UTCDateTime(p_arrival).strftime('%Y-%m-%d %H:%M:%S') if p_arrival else 'N/A'
            
            title = (
                f"{base_title}<br>"
                f"<sup>Distance: {dist['km']} km ({dist['deg']}°) | "
                f"P-Arrival: {p_time}</sup>"
            )
        else:
            title = base_title
            
        return title
    def render(self):
        self.display_waveform_data()
        self.filter_menu.update_available_channels(self.waveforms)

class WaveformComponents:
    settings: SeismoLoaderSettings
    filter_menu: WaveformFilterMenu
    waveform_display: WaveformDisplay

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.filter_menu = WaveformFilterMenu(settings)
        self.waveform_display = WaveformDisplay(settings, self.filter_menu)

    def render(self):
        st.title("Waveform Analysis")
        
        # Get Waveforms button
        if st.button("Get Waveforms"):
            self.waveform_display.retrieve_waveforms()
        
        # Render filter menu
        self.filter_menu.render()
        
        # Render waveform display
        self.waveform_display.render()
        
        if self.waveform_display.waveforms:
            distance_display = SeismicDistanceDisplay(
                self.waveform_display.waveforms,
                self.settings
            )
            distance_display.render()


class SeismicDistanceDisplay:
    def __init__(self, waveforms, settings):
        self.waveforms = waveforms
        self.settings = settings
        
    def calculate_distances(self):
        """Calculate distances between events and stations"""
        distances = []
        
        if not self.settings.event.selected_catalogs:
            return []
            
        # Get the first event (assuming single event for now)
        event = self.settings.event.selected_catalogs[0]
        event_lat = event.origins[0].latitude
        event_lon = event.origins[0].longitude
        event_depth = event.origins[0].depth / 1000  # Convert to km
        
        for waveform in self.waveforms:
            # Find corresponding station in inventory
            for network in self.settings.station.selected_invs:
                if network.code == waveform['Network']:
                    for station in network:
                        if station.code == waveform['Station']:
                            # Calculate distance
                            dist_deg = locations2degrees(
                                event_lat, event_lon,
                                station.latitude, station.longitude
                            )
                            dist_km = degrees2kilometers(dist_deg)
                            
                            distances.append({
                                'Network': waveform['Network'],
                                'Station': waveform['Station'],
                                'Distance_deg': round(dist_deg, 2),
                                'Distance_km': round(dist_km, 2),
                                'P_Arrival': waveform.get('P_Arrival'),
                                'Station_Lat': station.latitude,
                                'Station_Lon': station.longitude
                            })
                            break
                    break
                    
        return distances

    def display_distance_table(self, distances):
        """Display distance information in a table"""
        if not distances:
            st.warning("No distance information available.")
            return
            
        df = pd.DataFrame(distances)
        
        # Convert P_Arrival timestamps to human readable format
        df['P_Arrival'] = df['P_Arrival'].apply(
            lambda x: UTCDateTime(x).strftime('%Y-%m-%d %H:%M:%S') if pd.notnull(x) else None
        )
        
        st.subheader("Station Distances")
        
        # Create a styled dataframe with full width
        st.dataframe(
            df[['Network', 'Station', 'Distance_km', 'Distance_deg', 'P_Arrival']],
            column_config={
                'Distance_km': st.column_config.NumberColumn(
                    'Distance (km)',
                    help='Distance in kilometers',
                    format="%.2f"
                ),
                'Distance_deg': st.column_config.NumberColumn(
                    'Distance (°)',
                    help='Distance in degrees',
                    format="%.2f"
                ),
                'P_Arrival': st.column_config.TextColumn(
                    'P-Wave Arrival Time',
                    help='P-Wave arrival time in UTC',
                    width='large'
                )
            },
            hide_index=True,
            use_container_width=True  
        )

    def render(self):
        """Main render function"""
        st.title("Seismic Distance Analysis")
        
        # Calculate distances
        distances = self.calculate_distances()
        
        if not distances:
            st.warning("No distance information available. Please ensure both event and station data are loaded.")
            return
            
        self.display_distance_table(distances)
            