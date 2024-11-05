import os
import json

current_directory = os.path.dirname(os.path.abspath(__file__))


def save_original_client():
    """
    This method should be run at the entry point of the app.
    Once URL_MAPPINGS is modified, it applies it globally, 
    until the next run of the app.
    """
    from obspy.clients.fdsn.header import URL_MAPPINGS
    with open(os.path.join(current_directory,"orig_clients.json"), "w") as f:
        json.dump(URL_MAPPINGS, f, indent=4)

def load_original_client():
    if os.path.exists(os.path.join(current_directory,"orig_clients.json")):
        with open(os.path.join(current_directory,"orig_clients.json"), "r") as f:
            return json.load(f)    
    from obspy.clients.fdsn.header import URL_MAPPINGS
    return URL_MAPPINGS


def load_extra_client():
    if os.path.exists(os.path.join(current_directory,"extra_clients.json")):
        with open(os.path.join(current_directory,"extra_clients.json"), "r") as f:
            return json.load(f)
    return {}
        


def save_extra_client(extra_clients):
    orig_clients = load_original_client()
    to_save_extra_clients = {key: value for key, value in extra_clients.items() if key not in orig_clients}
    with open(os.path.join(current_directory,"extra_clients.json"), "w") as f:
        json.dump(to_save_extra_clients, f, indent=4)