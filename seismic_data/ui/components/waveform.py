import math
import re
from typing import List, Dict
from obspy import UTCDateTime
from seismic_data.models.config import SeismoLoaderSettings
from seismic_data.service.seismoloader import run_event
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
from obspy.geodetics import locations2degrees
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots


class WaveformFilterMenu:
    settings: SeismoLoaderSettings
    network_filter: str
    station_filter: str
    channel_filter: str

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.network_filter = "All networks"
        self.station_filter = "All stations"
        self.channel_filter = "All channels"

    def render(self):
        st.sidebar.header("Waveform Analysis Options")

        # Days per request
        self.settings.waveform.days_per_request = st.sidebar.number_input(
            "Days per request",
            value=self.settings.waveform.days_per_request,
            min_value=1,
            max_value=30,
        )

        # Network filter
        networks = ["All networks"] + list(set([inv.code for inv in self.settings.station.selected_invs]))
        self.network_filter = st.sidebar.selectbox(
            "Network:",
            networks
        )

        # Station filter
        stations = ["All stations"]
        for inv in self.settings.station.selected_invs:
            stations.extend([sta.code for sta in inv])
        stations = list(set(stations))
        stations.remove("All stations")
        stations.insert(0, "All stations")  # Ensure "All stations" is at the top
        self.station_filter = st.sidebar.selectbox(
            "Station:",
            stations,
            index=0  # Set default index to 0, which is "All stations"
        )

        # Channel filter
        channels = ["All channels", "BHE", "BHN", "BHZ"]  # Add more channels as needed
        self.channel_filter = st.sidebar.selectbox(
            "Channel:",
            channels
        )

        # Time window around P arrival
        st.sidebar.subheader("Time Window")
        self.settings.event.before_p_sec = st.sidebar.number_input(
            "Start (secs before P arrival):", 
            value=self.settings.event.before_p_sec, 
            step=1
        )
        self.settings.event.after_p_sec = st.sidebar.number_input(
            "End (secs after P arrival):", 
            value=self.settings.event.after_p_sec, 
            step=1
        )

        # Channel Preferences
        st.sidebar.subheader("Channel Preferences")
        self.settings.waveform.channel_pref = st.sidebar.multiselect(
            "Channel Preference",
            options=["CH", "HH", "BH", "EH", "HN", "EN", "SH", "LH"],
            default=self.settings.waveform.channel_pref,
        )

        # Location Preferences
        st.sidebar.subheader("Location Preferences")
        self.settings.waveform.location_pref = st.sidebar.multiselect(
            "Location Preference",
            options=["", "00", "10", "20", "30"],
            default=self.settings.waveform.location_pref,
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
        
        # self.prediction_data = self.settings.predictions
        # if waveform data is empty, don't even try to filter
        self.waveforms = run_event(self.settings)
        st.write("settings: ", self.settings)
        
        if not self.waveforms:
            st.warning("No waveforms retrieved. Please check your selection criteria.")
            return
        filtered_waveforms = [
            ts
            for ts in self.waveforms
            if re.match(r"^[A-Z]H[A-Z]?$", ts["Channel"])
            and ts["Data"] is not None
            and not ts["Data"].empty
        ]
        self.waveforms = filtered_waveforms
        if self.waveforms:
            st.success(f"Successfully retrieved {len(self.waveforms)} waveforms.")
        else:
            st.warning("No waveforms retrieved. Please check your selection criteria.")
        
        return None

    def display_waveform_data(self):
        if not self.waveforms:
            st.info(
                "No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms."
            )
            return

        all_waveforms = pd.DataFrame(self.waveforms)
        filtered_waveforms = self.apply_filters(all_waveforms)

        if filtered_waveforms.empty and len(all_waveforms) > 0:
            filtered_waveforms = all_waveforms

        # Pagination
        waveforms_per_page = 5
        num_pages = (len(filtered_waveforms) - 1) // waveforms_per_page + 1
        page = st.selectbox("Page top", range(1, num_pages + 1), key="top_pagination") - 1

        start_idx = page * waveforms_per_page
        end_idx = min((page + 1) * waveforms_per_page, len(filtered_waveforms))
        page_waveforms = filtered_waveforms.iloc[start_idx:end_idx]

        fig = make_subplots(
            rows=len(page_waveforms),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=[
                f"{w['Network']}.{w['Station']}.{w['Location']}.{w['Channel']}"
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

            # Create the trace for this waveform
            trace = go.Scatter(
                x=df["time"],
                y=df["amplitude"],
                mode="lines",
                name=f"{waveform['Network']}.{waveform['Station']}.{waveform['Location']}.{waveform['Channel']}",
                hovertemplate="Time: %{x}<br>Amplitude: %{y:.2f}<extra></extra>",
            )
            # Add the trace to the subplot
            fig.add_trace(trace, row=i, col=1)

        fig.update_layout(
            height=300 * len(page_waveforms),
            title_text=f"Seismic Waveforms (Page {page + 1} of {num_pages})",
            plot_bgcolor="white",
            margin=dict(l=100, r=100, t=150, b=100),
            legend=dict(yanchor="top", y=1.02, xanchor="left", x=1.05),
        )

        fig.update_xaxes(
            title_text="Time (UTC)",
            type="date",
            tickformat="%Y-%m-%d\n%H:%M:%S",
            gridcolor="lightgrey",
            row=len(page_waveforms),
            col=1,
        )

        st.plotly_chart(fig, use_container_width=True)
        
        # Display waveform information and data quality summary
        st.subheader("Waveform Information and Data Quality Summary")
        quality_summary = []
        for waveform in filtered_waveforms.to_dict("records"):
            df = waveform["Data"]
            non_zero_data = df[df["amplitude"] != 0]
            non_zero_percentage = (
                len(non_zero_data) / len(df) * 100 if not df.empty else 0
            )
            data_range = (
                df["amplitude"].max() - df["amplitude"].min() if not df.empty else 0
            )

            quality_summary.append(
                {
                    "Network": waveform["Network"],
                    "Station": waveform["Station"],
                    "Location": waveform["Location"],
                    "Channel": waveform["Channel"],
                    "Start Time": df["time"].min() if not df.empty else "N/A",
                    "End Time": df["time"].max() if not df.empty else "N/A",
                    "Duration": (
                        f"{(df['time'].max() - df['time'].min()).total_seconds():.2f} s"
                        if not df.empty
                        else "N/A"
                    ),
                    "Data Points": len(df),
                    "Non-zero Data (%)": f"{non_zero_percentage:.2f}%",
                    "Amplitude Range": f"{data_range:.2e}"
                }
            )
        st.dataframe(pd.DataFrame(quality_summary))

    def render(self):
        st.subheader("Download / Preview Waveforms")
        st.write(
            f"Number of selected events: {len(self.settings.event.selected_catalogs)}"
        )
        st.write(
            f"Number of selected stations: {len(self.settings.station.selected_invs)}"
        )
        
        if st.button("Get Waveforms"):
            self.retrieve_waveforms()
        self.display_waveform_data()

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
        self.filter_menu.render()
        self.waveform_display.render()




