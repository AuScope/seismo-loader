from obspy.clients.fdsn.header import URL_MAPPINGS

# Get a dictionary of available clients
def get_clients():
    return list(URL_MAPPINGS.keys())