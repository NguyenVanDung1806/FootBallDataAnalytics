import json
import pandas as pd
from geopy import Nominatim
import time
from geopy.exc import GeocoderTimedOut
import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup

NO_IMAGE = 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0a/No-image-available.png/480px-No-image-available.png'


def get_wikipedia_page(url):
    print("Getting wikipedia page...", url)

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # check if the request is successful
        return response.text
    except requests.RequestException as e:
        print(f"An error occurred: {e}")


def get_wikipedia_data(html):
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find_all("table", {"class": "wikitable"})[1]
    table_rows = table.find_all('tr')
    return table_rows


def clean_text(text):
    text = str(text).strip()
    text = text.replace('&nbsp', '')
    if text.find(' ♦'):
        text = text.split(' ♦')[0]
    if text.find('[') != -1:
        text = text.split('[')[0]
    if text.find(' (formerly)') != -1:
        text = text.split(' (formerly)')[0]

    return text.replace('\n', '')


def extract_wikipedia_data(**kwargs):
    url = kwargs['url']
    html = get_wikipedia_page(url)
    rows = get_wikipedia_data(html)

    data = []

    for i in range(1, len(rows)):
        tds = rows[i].find_all('td')
        values = {
            'rank': i,
            'stadium': clean_text(tds[0].text),
            'capacity': clean_text(tds[1].text).replace(',', '').replace('.', ''),
            'region': clean_text(tds[2].text),
            'country': clean_text(tds[3].text),
            'city': clean_text(tds[4].text),
            'images': 'https://' + tds[5].find('img').get('src').split("//")[1] if tds[5].find('img') else NO_IMAGE,
            'home_team': clean_text(tds[6].text),
        }
        data.append(values)

    json_rows = json.dumps(data)
    kwargs['ti'].xcom_push(key='rows', value=json_rows)

    return "OK"


def get_lat_long(country, city):
    geolocator = Nominatim(user_agent='geoapiExercises')
    try:
        location = geolocator.geocode(f'{city}, {country}')
        # Add a small delay to respect Nominatim's usage policy
        time.sleep(3)  # Sleep for 1 second between requests
        if location:
            return location.latitude, location.longitude
        return None
    except GeocoderTimedOut:
        print(f"Geocoding timed out for {city}, {country}. Retrying...")
        return get_lat_long(country, city)  # Retry if there's a timeout
    except Exception as e:
        print(f"Error geocoding {city}, {country}: {e}")
        return None


def transform_wikipedia_data(**kwargs):
    data = kwargs['ti'].xcom_pull(key='rows', task_ids='extract_data_from_wikipedia')

    data = json.loads(data)

    stadiums_df = pd.DataFrame(data)
    stadiums_df['location'] = stadiums_df.apply(lambda x: get_lat_long(x['country'], x['stadium']), axis=1)
    stadiums_df['images'] = stadiums_df['images'].apply(lambda x: x if x not in ['NO_IMAGE', '', None] else NO_IMAGE)

    # Handle missing or invalid data
    stadiums_df['stadium'] = stadiums_df['stadium'].fillna('Unknown Stadium')
    stadiums_df['country'] = stadiums_df['country'].fillna('Unknown Country')
    stadiums_df['city'] = stadiums_df['city'].fillna('Unknown City')
    stadiums_df['capacity'] = pd.to_numeric(stadiums_df['capacity'], errors='coerce').fillna(0).astype(int)

    # Handle duplicates
    duplicates = stadiums_df[stadiums_df.duplicated(['location'])]
    duplicates['location'] = duplicates.apply(lambda x: get_lat_long(x['country'], x['city']), axis=1)
    stadiums_df.update(duplicates)

    # Push to XCom
    kwargs['ti'].xcom_push(key='rows', value=stadiums_df.to_json())

    return "OK"


def write_wikipedia_data(**kwargs):
    data = kwargs['ti'].xcom_pull(key='rows', task_ids='transform_wikipedia_data')

    data = json.loads(data)
    data = pd.DataFrame(data)

    # Ensure the 'data' directory exists
    if not os.path.exists('data'):
        os.makedirs('data')

    file_name = ('stadium_cleaned_' + str(datetime.now().date())
                 + "_" + str(datetime.now().time()).replace(":", "_") + '.csv')

    data.to_csv('data/' + file_name, index=False)
    print(f"Data written to {file_name}")
    return "OK"
