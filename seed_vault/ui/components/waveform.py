import re
from typing import List, Dict
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from obspy import UTCDateTime
from seed_vault.enums.config import WorkflowType
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_continuous, run_event
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
from seed_vault.ui.components.display_log import ConsoleDisplay
import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from obspy.geodetics import degrees2kilometers
from obspy.geodetics.base import locations2degrees
import numpy as np
import threading
import queue
import time

class WaveformFilterMenu:
    settings: SeismoLoaderSettings
    network_filter: str
    station_filter: str
    channel_filter: str
    available_channels: List[str]
    display_limit: int
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.network_filter = "All networks"
        self.station_filter = "All stations"
        self.channel_filter = "All channels"
        self.available_channels = ["All channels"]
        self.display_limit = 5
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
        st.sidebar.title("Waveform Controls")
        
        # Step 1: Data Retrieval Settings
        with st.sidebar.expander("Step 1: Data Source", expanded=True):
            st.subheader("🔍 Time Window")
            self.settings.event.before_p_sec = st.number_input(
                "Start (secs before P arrival):", 
                value=20,
                help="Time window before P arrival"
            )
            self.settings.event.after_p_sec = st.number_input(
                "End (secs after P arrival):", 
                value=100,
                help="Time window after P arrival"
            )
            
            st.subheader("📡 Data Source")
            client_options = list(self.settings.client_url_mapping.keys())
            self.settings.waveform.client = st.selectbox(
                'Choose a client:', 
                client_options, 
                index=client_options.index(self.settings.waveform.client), 
                key="event-pg-client-event",
                help="Select the data source server"
            )

        # Step 2: Display Filters (enabled after data retrieval)
        with st.sidebar.expander("Step 2: Display Filters", expanded=True):
            if waveforms is not None:
                self.update_available_channels(waveforms)
                
                st.subheader("🎯 Waveform Filters")
                
                # Network filter
                networks = ["All networks"] + list(set([inv.code for inv in self.settings.station.selected_invs]))
                self.network_filter = st.selectbox(
                    "Network:",
                    networks,
                    index=networks.index(self.network_filter),
                    help="Filter by network"
                )
                
                # Station filter
                stations = ["All stations"]
                for inv in self.settings.station.selected_invs:
                    stations.extend([sta.code for sta in inv])
                stations = list(dict.fromkeys(stations))  # Remove duplicates
                stations.sort()
                
                self.station_filter = st.selectbox(
                    "Station:",
                    stations,
                    index=stations.index(self.station_filter),
                    help="Filter by station"
                )
                
                # Channel filter
                self.channel_filter = st.selectbox(
                    "Channel:",
                    options=self.available_channels,
                    index=self.available_channels.index(self.channel_filter),
                    help="Filter by channel"
                )
                
                st.subheader("📊 Display Options")
                self.display_limit = st.selectbox(
                    "Waveforms per page:",
                    options=[5, 10, 15],
                    index=[5, 10, 15].index(self.display_limit),
                    key="waveform_display_limit",
                    help="Number of waveforms to show per page"
                )
                
                # Add status information
                if waveforms:
                    st.sidebar.info(f"Total waveforms: {len(waveforms)}")
                    
                # Add reset filters button
                if st.sidebar.button("Reset Filters"):
                    self.network_filter = "All networks"
                    self.station_filter = "All stations"
                    self.channel_filter = "All channels"
                    self.display_limit = 5
            else:
                st.info("Load data to enable display filters")

class WaveformDisplay:
    settings: SeismoLoaderSettings
    waveforms: List[Dict] = []
    ttmodel: TauPyModel = None
    prediction_data: Dict[str, any] = {}
    filter_menu: WaveformFilterMenu

    def __init__(self, settings: SeismoLoaderSettings, filter_menu: WaveformFilterMenu):
        self.settings = settings
        self.filter_menu = filter_menu
        try:
            self.client = Client(self.settings.waveform.client)
        except ValueError as e:
            st.error(f"Error: {str(e)} Waveform client is set to {self.settings.waveform.client}, which seems does not exists. Please navigate to the settings page and use the Clients tab to add the client or fix the stored config.cfg file.")
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
        """Main waveform display function"""
        if not self.waveforms:
            st.info("No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms.")
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
        num_pages = (len(filtered_waveforms) - 1) // self.filter_menu.display_limit + 1
        page = st.sidebar.selectbox(
            "Page Navigation", 
            range(1, num_pages + 1), 
            key="sidebar_pagination"
        ) - 1

        start_idx = page * self.filter_menu.display_limit
        end_idx = min((page + 1) * self.filter_menu.display_limit, len(filtered_waveforms))
        page_waveforms = filtered_waveforms.iloc[start_idx:end_idx]

        fig = make_subplots(
            rows=len(page_waveforms),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=[
            self.create_subplot_title(w, distances)
                for w in page_waveforms.to_dict("records")
            ],
        )

        for i, waveform in enumerate(page_waveforms.to_dict("records"), 1):
            df = waveform["Data"]
            if df.empty:
                continue

            # Calculate scaling factor
            power = self._calculate_scaling_factor(df)
            
            # Create scaled trace
            trace = self._create_waveform_trace(df, power)
            fig.add_trace(trace, row=i, col=1)

            # Format y-axis
            y_min, y_max = df['amplitude'].min() / (10**power), df['amplitude'].max() / (10**power)
            self._format_counts_axis(fig, i, power, y_min, y_max)

            # Add P arrival marker if available
            if 'P_Arrival' in waveform and waveform['P_Arrival']:
                p_time = UTCDateTime(waveform['P_Arrival'])
                p_line = go.Scatter(
                    x=[p_time.datetime, p_time.datetime],
                    y=[y_min - (y_max - y_min) * 0.1, y_max + (y_max - y_min) * 0.1],
                    mode='lines',
                    line=dict(color='red', width=1, dash='dash'),
                    showlegend=False
                )
                fig.add_trace(p_line, row=i, col=1)

        fig.update_layout(
            height=300 * len(page_waveforms),
            title=dict(
                text=f"Seismic Waveforms (Page {page + 1} of {num_pages})",
                y=1,
                x=0.5,
                xanchor='center',
                yanchor='top'
            ),
            plot_bgcolor="white",
            margin=dict(l=50, r=50, t=100, b=50),
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
        # Add view selector at the top
        view_type = st.radio(
            "Select View Type",
            ["Default View", "Single Event - Multiple Stations", "Single Station - Multiple Events"],
            key="view_selector"
        )
        
        if not self.waveforms:
            st.info("No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms.")
            return

        # Update filter menu channels
        self.filter_menu.update_available_channels(self.waveforms)
        
        if view_type == "Default View":
            # Use the original display function
            self.display_waveform_data()
        elif view_type == "Single Event - Multiple Stations":
            events = self.settings.event.selected_catalogs
            event_options = [
                f"Event {i+1}: {event.origins[0].time} M{event.magnitudes[0].mag:.1f}"
                for i, event in enumerate(events)
            ]
            selected_event_idx = st.selectbox(
                "Select Event",
                range(len(event_options)),
                format_func=lambda x: event_options[x]
            )
            event = events[selected_event_idx]
            
            # Plot event view
            self.plot_event_view(event, self.waveforms)
        else:
            # Get unique stations
            stations = set((w['Network'], w['Station']) for w in self.waveforms)
            station_options = sorted([f"{net}.{sta}" for net, sta in stations])
            
            if not station_options:
                st.warning("No stations available.")
                return
                
            # Station selector
            selected_station = st.selectbox(
                "Select Station",
                station_options
            )
            net, sta = selected_station.split('.')
            
            # Filter waveforms for selected station
            station_waveforms = [
                w for w in self.waveforms
                if w['Network'] == net and w['Station'] == sta
            ]
            
            # Plot station view
            self.plot_station_view(selected_station, station_waveforms)
            
    def get_station_coordinates(self, network_code, station_code):
        """Get station coordinates from inventory"""
        for network in self.settings.station.selected_invs:
            if network.code == network_code:
                for station in network:
                    if station.code == station_code:
                        return (station.latitude, station.longitude)
        return None

    def create_event_subplot_title(self, event, waveform, distance_info):
        """Create subplot title for single event view"""
        dist_deg = distance_info['deg']
        dist_km = distance_info['km']
        p_arrival = waveform.get('P_Arrival')
        p_time = UTCDateTime(p_arrival).strftime('%H:%M:%S') if p_arrival else 'N/A'
        
        return (
            f"{waveform['Network']}.{waveform['Station']} | {waveform['Channel']} | "
            f"Δ: {dist_km:.0f} km ({dist_deg:.1f}°)<br>"
            f"<sup>P: {p_time}</sup>"
        )

    def create_station_subplot_title(self, event, waveform):
        """Create subplot title for single station view"""
        magnitude = event.magnitudes[0].mag
        depth = event.origins[0].depth/1000
        
        station_coords = self.get_station_coordinates(waveform['Network'], waveform['Station'])
        if station_coords:
            dist_deg = locations2degrees(
                event.origins[0].latitude,
                event.origins[0].longitude,
                station_coords[0],
                station_coords[1]
            )
            dist_km = degrees2kilometers(dist_deg)
        else:
            dist_deg = dist_km = "N/A"
        
        return (
            f"M{magnitude:.1f} | Depth: {depth:.1f} km | Δ: {dist_km:.0f} km ({dist_deg:.1f}°)<br>"
            f"<sup>{event.origins[0].time.strftime('%Y-%m-%d %H:%M:%S')}</sup>"
        )

    def add_pagination_to_sidebar(self, total_items):
        """Shared pagination logic"""
        num_pages = (total_items - 1) // self.filter_menu.display_limit + 1
        page = st.sidebar.selectbox(
            "Page Navigation", 
            range(1, num_pages + 1), 
            key="shared_pagination"
        ) - 1
        
        start_idx = page * self.filter_menu.display_limit
        end_idx = min((page + 1) * self.filter_menu.display_limit, total_items)
        
        return start_idx, end_idx, page, num_pages

    def plot_event_view(self, event, waveforms):
        """Plot single event with multiple stations"""
        if not waveforms:
            st.warning("No waveforms to display.")
            return

        # Calculate and sort by distances
        distances = {}
        for waveform in waveforms:
            station_coords = self.get_station_coordinates(waveform['Network'], waveform['Station'])
            if station_coords:
                dist_deg = locations2degrees(
                    event.origins[0].latitude,
                    event.origins[0].longitude,
                    station_coords[0],
                    station_coords[1]
                )
                dist_km = degrees2kilometers(dist_deg)
                distances[f"{waveform['Network']}.{waveform['Station']}"] = {
                    'deg': round(dist_deg, 2),
                    'km': round(dist_km, 2)
                }

        sorted_waveforms = sorted(waveforms, 
                                key=lambda w: distances.get(f"{w['Network']}.{w['Station']}", 
                                                         {'km': float('inf')})['km'])

        # Add pagination
        start_idx, end_idx, page, num_pages = self.add_pagination_to_sidebar(len(sorted_waveforms))
        page_waveforms = sorted_waveforms[start_idx:end_idx]

        # Create figure with paginated waveforms
        fig = make_subplots(
            rows=len(page_waveforms),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=[
                self.create_event_subplot_title(
                    event, 
                    w, 
                    distances[f"{w['Network']}.{w['Station']}"]
                ) for w in page_waveforms
            ]
        )

        # Rest of the plotting logic remains the same
        for annotation in fig.layout.annotations:
            annotation.update(y=annotation.y + 0.005)
        
        for i, waveform in enumerate(page_waveforms, 1):
            df = waveform['Data']
            if df.empty:
                continue

            # Calculate scaling factor
            power = self._calculate_scaling_factor(df)
            
            # Create scaled trace
            trace = self._create_waveform_trace(df, power)
            fig.add_trace(trace, row=i, col=1)

            # Format y-axis
            y_min, y_max = df['amplitude'].min() / (10**power), df['amplitude'].max() / (10**power)
            self._format_counts_axis(fig, i, power, y_min, y_max)

            # Add P arrival marker
            if waveform.get('P_Arrival'):
                p_time = UTCDateTime(waveform['P_Arrival'])
                p_line = go.Scatter(
                    x=[p_time.datetime, p_time.datetime],
                    y=[y_min - (y_max - y_min) * 0.1, y_max + (y_max - y_min) * 0.1],
                    mode='lines',
                    line=dict(color='red', width=1, dash='dash'),
                    showlegend=False
                )
                fig.add_trace(p_line, row=i, col=1)
        
        height_per_trace = 250
        fig.update_layout(
            height=height_per_trace * len(page_waveforms) + 100,
            title=dict(
                text=(
                    f"Event: {event.origins[0].time.strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"M{event.magnitudes[0].mag:.1f} | "
                    f"Lat: {event.origins[0].latitude:.2f}° | "
                    f"Lon: {event.origins[0].longitude:.2f}° | "
                    f"Depth: {event.origins[0].depth/1000:.1f} km"
                    f" (Page {page + 1} of {num_pages})"
                ),
                y=1,
                x=0.5,
                xanchor='center',
                yanchor='top'
            ),
            showlegend=False,
            plot_bgcolor='white',
            margin=dict(l=50, r=50, t=100, b=50)
        )

        # Update axes
        for i in range(1, len(page_waveforms) + 1):
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor='lightgray',
                tickformat='%H:%M:%S',
                row=i,
                col=1
            )
        
        st.plotly_chart(fig, use_container_width=True)

    def plot_station_view(self, station_code, waveforms):
        """Plot single station with multiple events"""
        if not waveforms:
            st.warning("No waveforms to display.")
            return

        # Sort waveforms by time
        sorted_waveforms = sorted(waveforms, 
                                key=lambda w: UTCDateTime(w.get('P_Arrival', '2099-01-01')))

        # Add pagination
        start_idx, end_idx, page, num_pages = self.add_pagination_to_sidebar(len(sorted_waveforms))
        page_waveforms = sorted_waveforms[start_idx:end_idx]

        station_coords = self.get_station_coordinates(
            page_waveforms[0]['Network'], 
            page_waveforms[0]['Station']
        )

        # Create figure with paginated waveforms
        fig = make_subplots(
            rows=len(page_waveforms),
            cols=1,
            vertical_spacing=0.08,
            shared_xaxes=True,
            subplot_titles=[
                self.create_station_subplot_title(
                    self.settings.event.selected_catalogs[0],
                    w
                ) for w in page_waveforms
            ]
        )

        # Rest of the plotting logic remains the same
        for annotation in fig.layout.annotations:
            annotation.update(y=annotation.y + 0.005)
            
        for i, waveform in enumerate(page_waveforms, 1):
            df = waveform['Data']
            if df.empty:
                continue

            # Calculate scaling factor
            power = self._calculate_scaling_factor(df)
            
            # Create scaled trace
            trace = self._create_waveform_trace(df, power)
            fig.add_trace(trace, row=i, col=1)

            # Format y-axis
            y_min, y_max = df['amplitude'].min() / (10**power), df['amplitude'].max() / (10**power)
            self._format_counts_axis(fig, i, power, y_min, y_max)

            # Add P arrival marker
            if waveform.get('P_Arrival'):
                p_time = UTCDateTime(waveform['P_Arrival'])
                p_line = go.Scatter(
                    x=[p_time.datetime, p_time.datetime],
                    y=[y_min - (y_max - y_min) * 0.1, y_max + (y_max - y_min) * 0.1],
                    mode='lines',
                    line=dict(color='red', width=1, dash='dash'),
                    showlegend=False
                )
                fig.add_trace(p_line, row=i, col=1)
        
        fig.update_layout(
            height=250 * len(page_waveforms) + 150,
            title=dict(
                text=(
                    f"Station: {station_code} | "
                    f"Lat: {station_coords[0]:.2f}° | "
                    f"Lon: {station_coords[1]:.2f}° "
                    f"(Page {page + 1} of {num_pages})"
                ),
                y=1,
                x=0.5,
                xanchor='center',
                yanchor='top'
            ),
            showlegend=False,
            plot_bgcolor='white',
            margin=dict(l=50, r=50, t=100, b=50)
        )

        for i in range(1, len(page_waveforms) + 1):
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor='lightgray',
                tickformat='%H:%M:%S',
                row=i,
                col=1,
            )
        st.plotly_chart(fig, use_container_width=True)

    def add_traces_to_figure(self, fig, waveforms):
        """Add waveform traces and P-arrival markers to figure"""
        for i, waveform in enumerate(waveforms, 1):
            df = waveform['Data']
            if df.empty:
                continue

            # Add waveform trace
            trace = go.Scatter(
                x=df["time"],
                y=df["amplitude"],
                mode="lines",
                line=dict(width=1),
                showlegend=False
            )
            fig.add_trace(trace, row=i, col=1)

            # Add P arrival marker if available
            if waveform.get('P_Arrival'):
                p_time = UTCDateTime(waveform['P_Arrival'])
                y_min, y_max = df['amplitude'].min(), df['amplitude'].max()
                margin = (y_max - y_min) * 0.1

                p_line = go.Scatter(
                    x=[p_time.datetime, p_time.datetime],
                    y=[y_min - margin, y_max + margin],
                    mode='lines',
                    line=dict(color='red', width=1, dash='dash'),
                    showlegend=False
                )
                fig.add_trace(p_line, row=i, col=1)

                # Update y-axis range
                fig.update_yaxes(
                    range=[y_min - margin, y_max + margin],
                    row=i,
                    col=1,
                    showgrid=True,
                    gridwidth=1,
                    gridcolor='lightgray'
                )

    def _calculate_scaling_factor(self, data):
        """Calculate appropriate scaling factor for the data"""
        max_abs = max(abs(data['amplitude'].max()), abs(data['amplitude'].min()))
        if max_abs == 0:
            return 0
        power = int(np.floor(np.log10(max_abs)))
        return power

    def _format_counts_axis(self, fig, row, power, y_min, y_max):
        """Format y-axis with proper scientific notation"""
        margin = (y_max - y_min) * 0.1
        fig.update_yaxes(
            title=f'Counts (×10<sup>{power}</sup>)',
            range=[y_min - margin, y_max + margin],
            tickformat='.1f',
            row=row,
            col=1,
            gridcolor='lightgrey',
            showgrid=True
        )

    def _create_waveform_trace(self, df, power):
        """Create a waveform trace with scaled data"""
        scaled_amplitude = df['amplitude'] / (10 ** power)
        return go.Scatter(
            x=df["time"],
            y=scaled_amplitude,
            mode="lines",
            line=dict(width=1),
            showlegend=False,
            hovertemplate="Time: %{x}<br>Counts: %{y:.2f}×10<sup>" + str(power) + "</sup><extra></extra>"
        )

class WaveformComponents:
    settings: SeismoLoaderSettings
    filter_menu: WaveformFilterMenu
    waveform_display: WaveformDisplay
    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.filter_menu = WaveformFilterMenu(settings)
        self.waveform_display = WaveformDisplay(settings, self.filter_menu)
        self.console_display = ConsoleDisplay()
        
    def render(self):
        if self.settings.selected_workflow == WorkflowType.CONTINUOUS:
            st.title("Continuous Waveform Processing")
            
            # Add calendar selection for start_time and end_time
            st.sidebar.subheader("Time Selection")
            self.settings.station.date_config.start_time = st.sidebar.date_input(
                "Start Time",
                value=self.settings.station.date_config.start_time,
                help="Select the start time for processing"
            )
            self.settings.station.date_config.end_time = st.sidebar.date_input(
                "End Time",
                value=self.settings.station.date_config.end_time,
                help="Select the end time for processing"
            )
            
            st.write('settings: ', self.settings)            
            if st.button("Start Processing", key="start_continuous"):
                # Create a container for the terminal-style output
                result = self.console_display.run_with_logs(
                    process_func=lambda: run_continuous(self.settings),
                    status_message="Processing continuous waveform data..."
                )
                
                if result:
                    st.success("Processing completed successfully!")
        else:
            st.title("Waveform Analysis")
            
            # Always render filter menu first
            self.filter_menu.render(self.waveform_display.waveforms)
            
            if st.button("Get Waveforms", key="get_waveforms"):
                self.waveform_display.retrieve_waveforms()
            
            # Display waveforms if they exist
            if self.waveform_display.waveforms:
                self.waveform_display.render()
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
            