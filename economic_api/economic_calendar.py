import json
from datetime import datetime, timedelta
import pytz


# Load the economic events from the JSON file
def load_economic_events():
    with open("economic_api/economic_events.json", "r") as f:
        return json.load(f)


# Function to check for economic events within 5 minutes of the current time
def check_economic_events(instrument_currency, current_time):
    events = load_economic_events()
    high_impact_events = []

    # Get current date to use when constructing event time
    current_date = current_time.strftime('%Y-%m-%d')

    for event in events:
        # Parse the event time, attach current date to avoid '1900-01-01' default
        event_time_str = f"{current_date} {event['time']}"
        event_time = datetime.strptime(event_time_str, "%Y-%m-%d %I:%M %p EST")

        # Localize the event time to Eastern time
        event_time = pytz.timezone('America/New_York').localize(event_time)

        # Check if the event impacts the instrument's currency and has high impact
        if event['currency'] == instrument_currency and event['impact'] == 'high':
            # Calculate the time window: 5 minutes before and after the event
            event_window_start = event_time - timedelta(minutes=5)
            event_window_end = event_time + timedelta(minutes=5)

            # Debugging: Print the current time and event window
            print(f"Current time: {current_time}")
            print(f"Event time: {event_time} for currency {event['currency']} with impact {event['impact']}")
            print(f"Event window: {event_window_start} to {event_window_end}")

            # Check if the current time falls within the event window
            if event_window_start <= current_time <= event_window_end:
                high_impact_events.append(event)
                print(f"High impact event detected: {event}")

    return high_impact_events
