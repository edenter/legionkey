import requests
import json
from ics import Calendar, Event
from datetime import datetime
import os
import re
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
POST_URL = os.getenv("POST_URL")

def fetch_access_token():
    """
    Fetches the website HTML and extracts the accessToken.
    """
    url = "https://gaming.lenovo.com/game-key-drops/"
    print(f"Fetching access token from {url}...")
    try:
        response = requests.get(url)
        response.raise_for_status()
        content = response.text
        
        # Search for the token pattern: "accessToken":"..."
        match = re.search(r'"accessToken":"([^"]+)"', content)
        if match:
            token = match.group(1)
            print("Successfully extracted access token.")
            return token
        else:
            print("Could not find 'accessToken' in the page source.")
            return None
    except Exception as e:
        print(f"Error fetching access token: {e}")
        return None

# Headers for the POST request
HEADERS = json.loads(os.getenv("HEADERS"))

# Fetch and inject the dynamic token
token = fetch_access_token()
if token:
    HEADERS["authorization"] = f"Bearer {token}"
else:
    print("Warning: Using existing authorization header (if any) because dynamic fetch failed.")

# GraphQL payload for the POST request
POST_PAYLOAD = json.loads(os.getenv("POST_PAYLOAD"))


# --- File Paths ---
CLEANED_DATA_FILE = "cleaned_data.json"
ICS_FILE = "events.ics"

def fetch_data(url, payload, headers):
    """
    Sends a POST request to the specified URL with the given payload and headers.
    Returns the JSON response from the server.
    """
    print(f"Sending POST request to {url}...")
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        print("Successfully fetched data.")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None

def save_to_file(data, filename):
    """Saves the given data to a file as JSON."""
    print(f"Saving data to {filename}...")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Successfully saved data to {filename}.")

def load_from_file(filename):
    """Loads JSON data from a file if it exists."""
    if not os.path.exists(filename):
        print(f"File {filename} not found. Starting with an empty event list.")
        return []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            # Handle empty file case
            content = f.read()
            if not content:
                return []
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Could not read or parse {filename}: {e}. Starting fresh.")
        return []

def clean_data(raw_data):
    """
    Cleans and transforms the raw data from the GraphQL response.
    """
    if not raw_data or 'data' not in raw_data or 'posts' not in raw_data['data'] or 'nodes' not in raw_data['data']['posts']:
        print("No 'posts.nodes' found in the raw data. Nothing to clean.")
        return []

    cleaned_events = []
    for post in raw_data['data']['posts']['nodes']:
        cleaned_event = {
            'id': post.get('id'),
            'summary': post.get('title', 'No Title').replace('(Coming Soon) ', '').strip(),
            'description': post.get('description', '').strip(),
            'url': post.get('url', ''),
            'begin': None,
            'end': None
        }

        if 'fields' in post and post['fields']:
            for field in post['fields']:
                field_key = field.get('key')
                field_value_str = field.get('value')

                if field_value_str is None:
                    continue

                try:
                    # The value is a JSON-encoded string, so we parse it.
                    field_value = json.loads(field_value_str)
                except (json.JSONDecodeError, TypeError):
                    # If it's not valid JSON, use the string as is.
                    field_value = field_value_str

                if field_key == 'start_date':
                    cleaned_event['begin'] = field_value
                elif field_key == 'end_date':
                    cleaned_event['end'] = field_value

        # Only include events that have a start time
        if cleaned_event['begin']:
            cleaned_events.append(cleaned_event)
            
    print(f"Cleaned {len(cleaned_events)} events.")
    return cleaned_events

def create_ics_file(events, filename):
    """
    Creates an iCalendar (.ics) file from a list of event dictionaries.
    """
    print(f"Creating iCalendar file at {filename}...")
    cal = Calendar()
    for event_data in events:
        try:
            event = Event()
            event.uid = event_data['id']
            event.name = event_data['summary']
            
            event.begin = event_data['begin']
            if event_data['end']:
                event.end = event_data['end']
            
            event.description = event_data['description']
            
            if event_data['url']:
                event.url = event_data['url']
            
            cal.events.add(event)
        except Exception as e:
            print(f"Could not process event: {event_data.get('summary')}. Error: {e}")

    if not cal.events:
        print("No events to add to the calendar. ICS file will not be created.")
        return

    with open(filename, 'w', encoding='utf-8') as f:
        f.writelines(cal)
    print(f"Successfully created {filename} with {len(cal.events)} events.")

def main():
    """Main function to orchestrate the process."""
    
    # 1. Load existing events
    print(f"Loading existing events from {CLEANED_DATA_FILE}...")
    existing_events_list = load_from_file(CLEANED_DATA_FILE)
    events_dict = {event['id']: event for event in existing_events_list if event.get('id')}
    print(f"Loaded {len(events_dict)} existing events.")

    # 2. Fetch data from the API
    raw_response_data = fetch_data(POST_URL, POST_PAYLOAD, HEADERS)
    if not raw_response_data:
        print("No data fetched from API. Exiting.")
        return

    # 4. Clean the new data
    newly_cleaned_events = clean_data(raw_response_data)
    if not newly_cleaned_events:
        print("No new events were cleaned from the API response.")
    else:
        # 5. Merge new events into the existing dictionary
        updated_count = 0
        new_count = 0
        for event in newly_cleaned_events:
            event_id = event.get('id')
            if not event_id:
                continue
            
            if event_id in events_dict:
                updated_count += 1
            else:
                new_count += 1
            events_dict[event_id] = event
        print(f"Merged events: {new_count} new, {updated_count} updated.")

    # 6. Convert dictionary back to a list for saving
    final_events_list = list(events_dict.values())
    
    # 7. Save the consolidated cleaned data
    save_to_file(final_events_list, CLEANED_DATA_FILE)

    # 8. Create the .ics file from the consolidated list
    create_ics_file(final_events_list, ICS_FILE)
    
    print("\nProcess finished.")
    print(f"- Cleaned data updated in: {CLEANED_DATA_FILE} ({len(final_events_list)} total events)")
    print(f"- iCalendar file recreated: {ICS_FILE}")


if __name__ == "__main__":
    # Before running, make sure you have installed the required libraries:
    # pip install requests ics
    main()
