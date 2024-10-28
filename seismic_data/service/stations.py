"""
The stations service should get the stations based on a selection (filter) settings.
UI should generate the selection and pass it here. We need a single function
here that gets the selection and runs Rob's script.

We should also be able to support multi-select areas.

@TODO: For now, dummy scripts are used. @Yunlong to fix.
"""

import pandas as pd
import streamlit as st
import requests
from obspy.core.inventory import Inventory, Network

from seismic_data.models.config import SeismoLoaderSettings
from seismic_data.service.seismoloader import get_stations



# @st.cache_data
# def get_station_data(settings_json_str: str):

#     settings = SeismoLoaderSettings.model_validate_json(settings_json_str)
#     return get_stations(settings)

def remove_duplicate_inventories(inventories):
    # Define a set to track unique network-station pairs
    unique_network_station_pairs = set()

    # Create lists to store the filtered networks and stations
    filtered_networks = []

    for network in inventories:
        unique_stations = []
        
        for station in network:
            # Create a tuple representing the network-station pair
            network_station_pair = (network.code, station.code)

            # If this network-station pair is unique, add it to the set and the list
            if network_station_pair not in unique_network_station_pairs:
                unique_network_station_pairs.add(network_station_pair)
                unique_stations.append(station)
        
        # If there are unique stations for this network, add a new network with filtered stations
        if unique_stations:
            filtered_network = Network(
                code=network.code,
                stations=unique_stations,
                description=network.description,
                start_date=network.start_date,
                end_date=network.end_date,
                total_number_of_stations=len(unique_stations),
            )
            filtered_networks.append(filtered_network)

    # Create a new Inventory object with the filtered networks
    return Inventory(
        networks=filtered_networks,
        source=inventories.source
    )

# @st.cache_data
def get_station_data(settings: SeismoLoaderSettings):
    return remove_duplicate_inventories(get_stations(settings))


def station_response_to_df(inventory):
    """
    Convert ObsPy Inventory data into a DataFrame with station information.
    """
    records = []
    for network in inventory.networks:
        for station in network.stations:
            station_code = station.code
            station_name = station.site.name
            latitude = station.latitude
            longitude = station.longitude
            elevation = station.elevation

            record = {
                'network': network.code,
                'station': station_code,
                'station_name': station_name,
                'latitude': latitude,
                'longitude': longitude,
                'elevation': elevation,
                # 'detail': station,
            }

            records.append(record)

            
            # for channel in station.channels:
            #     channel_code = channel.code
            #     channel_location = channel.location_code
            #     depth = channel.depth
            #     sensor = channel.sensor.description

            #     record = {
            #         'network': network.code,
            #         'station': station_code,
            #         'station_name': station_name,
            #         'latitude': latitude,
            #         'longitude': longitude,
            #         'elevation': elevation,
            #         'channel': channel_code,
            #         'location': channel_location,
            #         'depth': depth,
            #         'sensor': sensor
            #     }

            #     records.append(record)

    return pd.DataFrame(records)
