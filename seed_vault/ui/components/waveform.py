from typing import List
from obspy import Stream
from obspy import UTCDateTime
from seed_vault.enums.config import WorkflowType
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service.seismoloader import run_continuous, run_event
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
from seed_vault.ui.components.display_log import ConsoleDisplay
import streamlit as st
import pandas as pd
from obspy.geodetics import degrees2kilometers
from obspy.geodetics.base import locations2degrees
import numpy as np
import matplotlib.pyplot as plt

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
    def update_available_channels(self, stream: Stream):
        if not stream:
            self.available_channels = ["All channels"]
            return
            
        channels = set()
        for tr in stream:
            channels.add(tr.stats.channel)
        self.available_channels = ["All channels"] + sorted(list(channels))
        
        # Reset channel filter if current selection is invalid
        if self.channel_filter not in self.available_channels:
            self.channel_filter = "All channels"
    
    def render(self, stream=None):
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
            if stream is not None:
                self.update_available_channels(stream)
                
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
                if stream:
                    st.sidebar.info(f"Total waveforms: {len(stream)}")
                    
                # Add reset filters button
                if st.sidebar.button("Reset Filters"):
                    self.network_filter = "All networks"
                    self.station_filter = "All stations"
                    self.channel_filter = "All channels"
                    self.display_limit = 5
            else:
                st.info("Load data to enable display filters")

class WaveformDisplay:
    def __init__(self, settings: SeismoLoaderSettings, filter_menu: WaveformFilterMenu):
        self.settings = settings
        self.filter_menu = filter_menu
        
        try:
            self.client = Client(self.settings.waveform.client)
        except ValueError as e:
            st.error(f"Error: {str(e)} Waveform client is set to {self.settings.waveform.client}, which seems does not exists. Please navigate to the settings page and use the Clients tab to add the client or fix the stored config.cfg file.")
        self.ttmodel = TauPyModel("iasp91")
        self.streams = [] 
    def apply_filters(self, stream: Stream) -> Stream:
        """Filter stream based on user selection"""
        filtered_stream = Stream()
        
        for tr in stream:
            if (self.filter_menu.network_filter == "All networks" or 
                tr.stats.network == self.filter_menu.network_filter) and \
               (self.filter_menu.station_filter == "All stations" or 
                tr.stats.station == self.filter_menu.station_filter) and \
               (self.filter_menu.channel_filter == "All channels" or 
                tr.stats.channel == self.filter_menu.channel_filter):
                filtered_stream += tr
                
        return filtered_stream
    def retrieve_waveforms(self):
        """Retrieve waveforms and store as ObsPy streams"""
        if not self.settings.event.selected_catalogs or not self.settings.station.selected_invs:
            st.warning("Please select events and stations before downloading waveforms.")
            return
            
        self.streams = run_event(self.settings)  # This now returns list of streams
        
        if self.streams:
            # Update filter menu with first stream
            self.filter_menu.update_available_channels(self.streams[0])
            st.success(f"Successfully retrieved waveforms for {len(self.streams)} events.")
        else:
            st.warning("No waveforms retrieved. Please check your selection criteria.")
            
    def _get_trace_color(self, index: int) -> str:
        """Get color for trace based on index"""
        # Define a color cycle - black, red, blue, green
        colors = ['black', 'red', 'blue', 'green']
        return colors[index % len(colors)]
    def _plot_stream_with_colors(self, stream: Stream, size=(800, 600)):
        """Plot stream with proper time windows and P markers"""
        if not stream:
            return None
        
        try:
            # Create figure with subplots
            num_traces = len(stream)
            fig, axes = plt.subplots(num_traces, 1, figsize=(size[0]/100, size[1]/100), sharex=True)
            if num_traces == 1:
                axes = [axes]
            
            # Process each trace
            for i, tr in enumerate(stream):
                ax = axes[i]
                
                # Get P arrival time
                p_time = UTCDateTime(tr.stats.p_arrival) if hasattr(tr.stats, 'p_arrival') else None
                
                if p_time:
                    # Calculate window boundaries
                    start_time = p_time - self.settings.event.before_p_sec
                    end_time = p_time + self.settings.event.after_p_sec
                    
                    # Ensure trace is trimmed to window
                    tr.trim(start_time, end_time, pad=True, fill_value=0)
                    
                    # Create time vector matching data length
                    times = np.linspace(-self.settings.event.before_p_sec, 
                                      self.settings.event.after_p_sec,
                                      len(tr.data))
                    
                    # Plot waveform
                    ax.plot(times, tr.data, '-', color=self._get_trace_color(i), linewidth=0.8)
                    
                    # Add P marker at t=0
                    ax.axvline(x=0, color='red', linewidth=1, linestyle='-')
                    ax.text(0, ax.get_ylim()[1], 'P', color='red', fontsize=8,
                           verticalalignment='bottom')
                    
                    # Format axis
                    ax.set_xlim(-self.settings.event.before_p_sec, 
                               self.settings.event.after_p_sec)
                    
                    # Add trace label
                    label = f'{tr.stats.network}.{tr.stats.station}.{tr.stats.channel}'
                    if hasattr(tr.stats, 'distance_km'):
                        label += f' ({tr.stats.distance_km:.1f} km)'
                    ax.text(-self.settings.event.before_p_sec * 0.95, 
                           ax.get_ylim()[1],
                           label,
                           fontsize=8)
                    
                    # Format time axis
                    if i == num_traces - 1:  # Only for bottom subplot
                        ax.set_xlabel('Time relative to P (seconds)')
                        # Add actual time labels
                        def format_time(x, p):
                            t = p_time + x
                            return t.strftime('%H:%M:%S')
                        ax.xaxis.set_major_formatter(plt.FuncFormatter(format_time))
                        plt.setp(ax.xaxis.get_majorticklabels(), rotation=20)
                else:
                    # If no P arrival, plot raw data
                    times = np.arange(len(tr.data)) * tr.stats.delta
                    ax.plot(times, tr.data, '-', color=self._get_trace_color(i), linewidth=0.8)
                    ax.text(0, ax.get_ylim()[1], 
                           f'{tr.stats.network}.{tr.stats.station}.{tr.stats.channel}',
                           fontsize=8)
                
                # Remove unnecessary ticks
                ax.set_yticks([])
                if i < num_traces - 1:
                    ax.set_xticklabels([])
                
                # Add amplitude scale
                max_amp = np.max(np.abs(tr.data))
                ax.text(self.settings.event.after_p_sec * 0.95, 
                       ax.get_ylim()[1],
                       f'{max_amp:.1e}',
                       fontsize=8,
                       horizontalalignment='right')
            
            # Add title
            plt.suptitle(f'Event Waveforms (P arrival at 0 seconds)\n'
                        f'Window: {self.settings.event.before_p_sec}s before to '
                        f'{self.settings.event.after_p_sec}s after P',
                        fontsize=10)
            
            plt.tight_layout()
            return fig
            
        except Exception as e:
            st.error(f"Error in plotting: {str(e)}")
            return None

    def plot_event_view(self, event, stream: Stream, page: int, num_pages: int):
        """Plot event view with proper time alignment"""
        if not stream:
            return
        
        # Sort traces by distance if available
        if hasattr(stream[0].stats, 'distance'):
            stream.traces.sort(key=lambda x: x.stats.distance)
        
        # Get current page's traces
        start_idx = page * self.filter_menu.display_limit
        end_idx = start_idx + self.filter_menu.display_limit
        current_stream = Stream(traces=stream.traces[start_idx:end_idx])
        
        # Trim traces to window around P
        for tr in current_stream:
            if hasattr(tr.stats, 'p_arrival'):
                p_time = UTCDateTime(tr.stats.p_arrival)
                window_start = p_time - self.settings.event.before_p_sec
                window_end = p_time + self.settings.event.after_p_sec
                tr.trim(window_start, window_end)
        
        # Create plot
        fig = self._plot_stream_with_colors(
            current_stream,
            size=(800, max(400, len(current_stream) * 100))
        )
        
        # Add event information
        event_info = (f"Event: {event.origins[0].time} "
                     f"M{event.magnitudes[0].mag:.1f} "
                     f"Page {page + 1} of {num_pages}")
        fig.suptitle(event_info)
        
        return fig

    def plot_station_view(self, station_code: str, stream: Stream, page: int, num_pages: int):
        """Plot station view with P arrivals"""
        if not stream:
            return
        
        # Sort traces by time
        stream.traces.sort(key=lambda x: x.stats.starttime)
        
        # Get current page's traces
        start_idx = page * self.filter_menu.display_limit
        end_idx = start_idx + self.filter_menu.display_limit
        current_stream = Stream(traces=stream.traces[start_idx:end_idx])
        
        # Plot using ObsPy
        fig = self._plot_stream_with_colors(current_stream, size=(800, max(400, len(current_stream) * 100)))
        
        # Add station information
        fig.suptitle(f"Station: {station_code} Page {page + 1} of {num_pages}")
        fig.tight_layout()
        return fig

    def display_waveform_data(self):
        """Display default view with P arrivals"""
        if not self.streams:
            st.info("No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms.")
            return

        # Update filter menu channels before displaying
        self.filter_menu.update_available_channels(self.streams[0])
        
        # Apply filters to first stream
        filtered_stream = self.apply_filters(self.streams[0])
        
        if len(filtered_stream) == 0:
            st.warning("No waveforms match the current filter criteria.")
            return

        # Calculate pagination
        num_pages = (len(filtered_stream) - 1) // self.filter_menu.display_limit + 1
        page = st.sidebar.selectbox(
            "Page Navigation", 
            range(1, num_pages + 1),
            key="default_view_pagination"
        ) - 1

        # Plot waveforms for current page
        start_idx = page * self.filter_menu.display_limit
        end_idx = start_idx + self.filter_menu.display_limit
        current_stream = Stream(traces=filtered_stream.traces[start_idx:end_idx])
        
        fig = self._plot_stream_with_colors(current_stream, size=(800, max(400, len(current_stream) * 100)))
        
        fig.suptitle(f'Page {page + 1} of {num_pages}')
        fig.tight_layout()
        
        if fig:
            st.pyplot(fig)
        else:
            st.warning("No waveforms to display for the current selection.")

    def render(self):
        view_type = st.radio(
            "Select View Type",
            ["Default View", "Single Event - Multiple Stations", "Single Station - Multiple Events"],
            key="view_selector"
        )
        
        if not self.streams:
            st.info("No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms.")
            return

        if view_type == "Default View":
            self.display_waveform_data()
        
        elif view_type == "Single Event - Multiple Stations":
            events = self.settings.event.selected_catalogs
            if not events:
                st.warning("No events available.")
                return
            
            event_options = [
                f"Event {i+1}: {event.origins[0].time} M{event.magnitudes[0].mag:.1f}"
                for i, event in enumerate(events)
            ]
            selected_event_idx = st.selectbox(
                "Select Event",
                range(len(event_options)),
                format_func=lambda x: event_options[x]
            )
            
            if self.streams and len(self.streams) > selected_event_idx:
                stream = self.streams[selected_event_idx]
                filtered_stream = self.apply_filters(stream)
                
                if len(filtered_stream) > 0:
                    # Calculate pagination
                    num_pages = (len(filtered_stream) - 1) // self.filter_menu.display_limit + 1
                    page = st.sidebar.selectbox(
                        "Page Navigation", 
                        range(1, num_pages + 1),
                        key="event_view_pagination"
                    ) - 1
                    
                    # Use plot_event_view instead of plot_aligned_traces
                    fig = self.plot_event_view(
                        events[selected_event_idx],
                        filtered_stream,
                        page,
                        num_pages
                    )
                    if fig:
                        st.pyplot(fig)
                else:
                    st.warning("No waveforms match the current filter criteria.")
                
        else:  # Single Station - Multiple Events view
            if not self.streams:
                st.warning("No streams available.")
                return
            
            # Get unique stations from all streams
            stations = set()
            for stream in self.streams:
                filtered_stream = self.apply_filters(stream)
                for tr in filtered_stream:
                    stations.add(f"{tr.stats.network}.{tr.stats.station}")
            
            if not stations:
                st.warning("No stations match the current filter criteria.")
                return
            
            station_options = sorted(list(stations))
            selected_station = st.selectbox(
                "Select Station",
                station_options
            )
            
            if selected_station:
                net, sta = selected_station.split(".")
                # Collect all traces for selected station
                station_stream = Stream()
                for stream in self.streams:
                    filtered_stream = self.apply_filters(stream)
                    for tr in filtered_stream:
                        if tr.stats.network == net and tr.stats.station == sta:
                            station_stream += tr
                
                if station_stream:
                    # Calculate pagination
                    num_pages = (len(station_stream) - 1) // self.filter_menu.display_limit + 1
                    page = st.sidebar.selectbox(
                        "Page Navigation", 
                        range(1, num_pages + 1),
                        key="station_view_pagination"
                    ) - 1
                    
                    # Use plot_station_view
                    fig = self.plot_station_view(selected_station, station_stream, page, num_pages)
                    if fig:
                        st.pyplot(fig)
                else:
                    st.warning("No waveforms available for the selected station.")

    def plot_aligned_traces(self, stream: Stream, time_before: int = 10, time_after: int = 60):
        """Plot traces aligned on P arrival using ObsPy's native plotting"""
        if not stream or len(stream) == 0:
            st.warning("No traces available in stream")
            return None
        
        st_aligned = Stream()
        
        # Align traces on P arrival
        for tr in stream:
            if not hasattr(tr.stats, 'p_arrival'):
                st.write(f"❌ No P arrival for this trace")
                continue
            
            try:
                if isinstance(tr.stats.p_arrival, (int, float)):
                    p_time = UTCDateTime(tr.stats.p_arrival)
                else:
                    p_time = tr.stats.p_arrival
                    
                # Calculate P arrival relative to trace start
                p_relative = p_time - tr.stats.starttime
                
                # Calculate trim window
                start_time = tr.stats.starttime + p_relative - time_before
                end_time = tr.stats.starttime + p_relative + time_after
                
                # Ensure trim window is within trace bounds
                if start_time < tr.stats.starttime:
                    start_time = tr.stats.starttime
                if end_time > tr.stats.endtime:
                    end_time = tr.stats.endtime
                
                tr_cut = tr.copy()
                tr_cut.trim(start_time, end_time)
                
                if tr_cut.stats.npts > 0:
                    # Normalize the trace
                    tr_cut.data = tr_cut.data / np.max(np.abs(tr_cut.data))
                    # Add P arrival time as trace attribute for plotting
                    tr_cut.stats.p_relative = p_relative
                    st_aligned += tr_cut
                else:
                    st.write("❌ Trimmed trace has zero length")
                    continue
                    
            except Exception as e:
                st.write(f"❌ Error processing trace: {str(e)}")
                continue
        
        if not st_aligned or len(st_aligned) == 0:
            st.warning("No traces could be aligned on P arrivals. Please ensure P arrivals are calculated.")
            return None
        
        try:
            # Sort traces by distance if available
            st_aligned.traces.sort(key=lambda x: x.stats.distance_km if hasattr(x.stats, 'distance_km') else 0)
            
            # Use ObsPy's plot method
            fig = st_aligned.plot(
                type='relative',
                equal_scale=False,
                show=False,
                size=(800, max(400, len(st_aligned) * 100)),  # Adjust height based on number of traces
                method='full'
            )
            
            # Add title and P arrival markers
            ax = fig.axes[0]
            ax.set_title(f'P-Wave Aligned View ({len(st_aligned)} traces)\nRed line marks P arrival')
            
            # Add vertical line at P arrival (time_before seconds mark)
            for ax in fig.axes:
                ax.axvline(x=time_before, color='red', linestyle='-', linewidth=1.5)
                ax.text(time_before, ax.get_ylim()[1], 'P', color='red', fontsize=8)
            
            fig.tight_layout()
            return fig
            
        except Exception as e:
            st.error(f"Error plotting aligned traces: {str(e)}")
            st.write(f"Number of aligned traces: {len(st_aligned)}")
            return None

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
                result = self.console_display.run_with_logs(
                    process_func=lambda: run_continuous(self.settings),
                    status_message="Processing continuous waveform data..."
                )
                
                if result:
                    st.success("Processing completed successfully!")
        else:
            st.title("Waveform Analysis")
            
            # Get Waveforms button should be before filter menu render
            if st.button("Get Waveforms", key="get_waveforms"):
                self.waveform_display.retrieve_waveforms()
                # Force a rerun to update the UI immediately
                st.rerun()
            
            # Render filter menu with current stream
            current_stream = self.waveform_display.streams[0] if self.waveform_display.streams else None
            self.filter_menu.render(current_stream)
            
            # Display waveforms if they exist
            if self.waveform_display.streams:
                self.waveform_display.render()
                distance_display = SeismicDistanceDisplay(
                    self.waveform_display.streams,
                    self.settings
                )
                distance_display.render()


class SeismicDistanceDisplay:
    def __init__(self, streams: List[Stream], settings: SeismoLoaderSettings):
        """Initialize with ObsPy streams instead of waveform dictionaries"""
        self.streams = streams
        self.settings = settings
        
    def calculate_distances(self):
        """Calculate distances between events and stations using stream metadata"""
        distances = []
        
        if not self.settings.event.selected_catalogs:
            return []
            
        # Get the first event
        event = self.settings.event.selected_catalogs[0]
        event_lat = event.origins[0].latitude
        event_lon = event.origins[0].longitude
        event_depth = event.origins[0].depth / 1000  # Convert to km
        
        # Use the first stream (corresponding to first event)
        if not self.streams:
            return []
            
        stream = self.streams[0]
        for tr in stream:
            # Find corresponding station in inventory
            for network in self.settings.station.selected_invs:
                if network.code == tr.stats.network:
                    for station in network:
                        if station.code == tr.stats.station:
                            # Calculate distance if not already in trace stats
                            if not hasattr(tr.stats, 'distance_deg'):
                                dist_deg = locations2degrees(
                                    event_lat, event_lon,
                                    station.latitude, station.longitude
                                )
                                dist_km = degrees2kilometers(dist_deg)
                            else:
                                dist_deg = tr.stats.distance_deg
                                dist_km = tr.stats.distance_km
                            
                            distances.append({
                                'Network': tr.stats.network,
                                'Station': tr.stats.station,
                                'Distance_deg': round(dist_deg, 2),
                                'Distance_km': round(dist_km, 2),
                                'P_Arrival': tr.stats.p_arrival if hasattr(tr.stats, 'p_arrival') else None,
                                'Station_Lat': station.latitude,
                                'Station_Lon': station.longitude
                            })
                            break
                    break
                    
        return distances

    def render(self):
        """Render the distance display (implement as needed)"""
        distances = self.calculate_distances()
        if distances:
            st.subheader("Station Distances")
            df = pd.DataFrame(distances)
            st.dataframe(df)
