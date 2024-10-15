import math
import re
from typing import List, Dict
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
    event_filter: str
    network_filter: str
    station_filter: str

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self.event_filter = "All events"
        self.network_filter = "All networks"
        self.station_filter = "All stations"

    def render(self):
        st.sidebar.header("Waveform Analysis Options")

        # Days per request
        self.settings.waveform.days_per_request = st.sidebar.number_input(
            "Days per request",
            value=self.settings.waveform.days_per_request,
            min_value=1,
            max_value=30,
        )

        # Event filter
        event_times = ["All events"] + [ev.origins[0].time.isoformat() for ev in self.settings.event.selected_catalogs]
        self.event_filter = st.sidebar.selectbox(
            "Event:",
            event_times
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
        self.station_filter = st.sidebar.selectbox(
            "Station:",
            stations
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
        if self.filter_menu.event_filter != "All events":
            df = df[df["Event Time"] == self.filter_menu.event_filter]
        if self.filter_menu.network_filter != "All networks":
            df = df[df["Network"] == self.filter_menu.network_filter]
        if self.filter_menu.station_filter != "All stations":
            df = df[df["Station"] == self.filter_menu.station_filter]
        return df
    
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
        self.prediction_data = self.settings.predictions

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
    def apply_filters(self, df):
        if self.filter_menu.event_filter != "All events":
            df = df[df["Event Time"] == self.filter_menu.event_filter]
        if self.filter_menu.network_filter != "All networks":
            df = df[df["Network"] == self.filter_menu.network_filter]
        if self.filter_menu.station_filter != "All stations":
            df = df[df["Station"] == self.filter_menu.station_filter]
        return df

    def display_waveform_data(self):
        if not self.waveforms:
            st.info(
                "No waveforms to display. Use the 'Get Waveforms' button to retrieve waveforms."
            )
            return

        filtered_waveforms = self.apply_filters(pd.DataFrame(self.waveforms))

        if filtered_waveforms.empty:
            st.warning("No waveforms match the current filters.")
            return

        # Pagination
        waveforms_per_page = 5
        num_pages = (len(filtered_waveforms) - 1) // waveforms_per_page + 1
        page = st.selectbox("Page", range(1, num_pages + 1)) - 1

        start_idx = page * waveforms_per_page
        end_idx = min((page + 1) * waveforms_per_page, len(filtered_waveforms))
        page_waveforms = filtered_waveforms.iloc[start_idx:end_idx]

        fig = make_subplots(
            rows=len(page_waveforms),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
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
            # Look up the prediction for this waveform
            event_id = self.filter_menu.event_filter if self.filter_menu.event_filter != "All events" else self.settings.event.selected_catalogs[0].resource_id.id
            station_id = f"{waveform['Network']}.{waveform['Station']}"
            prediction_key = f"{event_id}|{station_id}"

            if prediction_key in self.prediction_data:
                prediction = self.prediction_data[prediction_key]
                p_arrival = prediction.p_arrival

                # Add P arrival line (vertical)
                fig.add_vline(
                    x=p_arrival, 
                    line_width=2, 
                    line_dash="dash", 
                    line_color="red",
                    row=i, 
                    col=1
                )

                # Add annotations for P and S arrivals
                fig.add_annotation(
                    x=p_arrival,
                    y=1,
                    yref="paper",
                    text="P",
                    showarrow=False,
                    font=dict(color="red"),
                    row=i,
                    col=1,
                )
            # Add the trace to the subplot
            fig.add_trace(trace, row=i, col=1)

            # Update y-axis label and range
            y_range = [df["amplitude"].min(), df["amplitude"].max()]
            fig.update_yaxes(title_text="Amplitude", row=i, col=1, range=y_range)

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

        # Update y-axes
        fig.update_yaxes(
            gridcolor="lightgrey",
            zerolinecolor="red",
            zerolinewidth=1,
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
            event_id = self.filter_menu.event_filter if self.filter_menu.event_filter != "All events" else self.settings.event.selected_catalogs[0].resource_id.id
            station_id = f"{waveform['Network']}.{waveform['Station']}"
            prediction_key = f"{event_id}|{station_id}"

            p_arrival = "N/A"
            s_arrival = "N/A"
            if prediction_key in self.prediction_data:
                prediction = self.prediction_data[prediction_key]
                p_arrival = prediction.p_arrival.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                s_arrival = prediction.s_arrival.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

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
                    "Amplitude Range": f"{data_range:.2e}",
                    "Predicted P Arrival": p_arrival,
                    "Predicted S Arrival": s_arrival,
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
        # col1, col2, col3 = st.columns(3)
        # with col1:
        #     # TODO event is not time. check self.settings.event.selected_catalogs
        #     event_times = [ev.origins[0].time.isoformat() for ev in self.settings.event.selected_catalogs]
        #     self.event_filter = st.selectbox(
        #         "Event:",
        #         ["All events"] + event_times
        #     )

        # with col2:
        #     self.network_filter = st.selectbox(
        #         "Network:",
        #         ["All networks"] + list(set([wf["Network"] for wf in self.waveforms])),
        #     )
        # with col3:
        #     self.station_filter = st.selectbox(
        #         "Station:",
        #         ["All stations"] + list(set([wf["Station"] for wf in self.waveforms])),
        #     )

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




