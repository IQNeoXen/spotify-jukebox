import os
import time
import base64
from bs4 import BeautifulSoup
import re
import spotipy
import requests
import json
from bs4 import BeautifulSoup
from spotipy.oauth2 import SpotifyOAuth
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

##################################
#             CONFIG             #
##################################

# refresh time (seconds)
REFRESH_TIME = 5

# minimum tts amount
MIN_TTS_AMOUNT = 2

# minimum spotify amount
MIN_SPOTIFY_AMOUNT = 1

# minimum spotify skip amount
MIN_SPOTIFY_SKIP_AMOUNT = 5

# spotify mute volume during tts
SPOTIFY_MUTE_VOLUME = 40

# spotify volume after tts
SPOTIFY_MAX_VOLUME = 80

# Define your GOOGLE_SCOPES here
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Define your SPOTIFY_SCOPES here
SPOTIFY_SCOPES = "user-modify-playback-state,user-read-currently-playing"

# words in this list will mark any message as a bar transaction and thus skip TTS
BAR_TRANSACTION_IDENTIFIER_WORDS = [
    "bar",
    "bier",
    "shot",
    "shots",
    "drink",
    "drinks",
    "jägi",
    "jägermeister",
    "getränk",
    "cocktail",
    "wein",
    "schnaps",
    "whiskey",
    "wodka",
    "gin",
    "rum",
    "tequila",
    "prosecco",
    "sekt",
    "champagner",
    "liquor",
    "pils",
    "lager",
    "radler",
    "apfelwein",
    "weinschorle",
    "cola",
    "limonade",
    "wasser",
    "saft",
    "sprudel",
    "espresso",
    "kaffee",
    "latte",
    "capuccino"
]

##################################

def authenticate_spotify(credentials_file="spotify_credentials.json"):
    # Load credentials
    with open(credentials_file, "r") as file:
        credentials = json.load(file)["credentials"]

    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]
    redirect_uri = credentials["redirect_uri"]

    # Initialize SpotifyOAuth with the loaded credentials
    sp_oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SPOTIFY_SCOPES,
        cache_path="./spotify_credentials_cache.json",
    )
    token_info = sp_oauth.get_cached_token()

    if not token_info:
        auth_url = sp_oauth.get_authorize_url()
        print(f"Please navigate here in your browser: {auth_url}")
        response = input("Enter the URL you were redirected to: ")
        code = sp_oauth.parse_response_code(response)
        token_info = sp_oauth.get_access_token(code)

    sp = spotipy.Spotify(auth=token_info["access_token"])
    return sp

# def authenticate_polly(credentials_file="polly_credentials.json"):
#     # Load credentials
#     with open(credentials_file, "r") as file:
#         credentials = json.load(file)["credentials"]

#     aws_access_key_id = credentials["aws_access_key_id"]
#     aws_secret_access_key = credentials["aws_secret_access_key"]

#     polly_client = boto3.client('polly', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key, region_name='us-east-1')
#     return polly_client

def add_track_to_queue(sp, track_url):
    try:
        # Extract the track ID from the URL
        track_id = track_url.split("/")[-1].split("?")[0]
        track_uri = f"spotify:track:{track_id}"
        sp.add_to_queue(uri=track_uri)
        print("Track added to queue successfully.")
    except Exception as e:
        print(f"An error occurred while queuing the spotify track_url {track_url}: {e}")

def skip_track(sp):
    try:
        sp.next_track()
        print("Skipped to the next track.")
    except Exception as e:
        print(f"An error occurred while skipping the track: {e}")

def find_skip(message, donation_amount):
    if message.strip().lower() == "skip" and donation_amount >= MIN_SPOTIFY_SKIP_AMOUNT:
        return True
    else:
        return False
    
def check_bar_transaction(message):
    try:
        message = message.lower()
        words = message.split()

        # if the message consists of more than 2 words, it's most likely not a bar transaction
        if len(words) > 2:
            return False

        for word in words:
            if word in BAR_TRANSACTION_IDENTIFIER_WORDS:
                return True

        # if the message is longer than 2 words and we didn't find any word indicating a bar transaction, this is most likely not one.
        return False
    except Exception as e:
        print(f"An error occurred while trying to check if it's a bar transaction: {e}")
        return False

def find_spotify_url(text):
    try:
        #Find and reconstruct the Spotify URL from HTML content, ignoring inserted whitespaces.

        # Define a regex pattern to match the malformed Spotify URL
        # This pattern looks for the 'spotify.com/track/' part, and allows for spaces between any characters in the URL.
        pattern = re.compile(r"open\.\s*spotify\.\s*com/track/\S+")

        # Search for the pattern in the extracted text
        match = pattern.search(text)
        if match:
            # If a match is found, remove unwanted spaces to reconstruct the URL
            url = re.sub(r"\s+", "", match.group())
            return url
        return None
    except Exception as e:
        print(f"An error occurred while trying to find a spotify URL: {e}")
        return None

def find_spotify_track_name(sp, track_url):
    try:
        # Extract the track ID from the URL
        track_id = track_url.split("/")[-1].split("?")[0]

        # Use the Spotify client to fetch the track's details
        track_details = sp.track(track_id)

        # Extract the track name
        track_name = track_details['name']

        # Extract the artist(s) names
        artists = [artist['name'] for artist in track_details['artists']]
        artist_names = ", ".join(artists)

        return f"{track_name} von {artist_names}"
    
    except Exception as e:
        print(f"An error occurred while fetching spotify track details: {e}")
        return None

def cut_string(tts_str):
    # Check if the string is longer than 200 characters
    if len(tts_str) > 200:
        # Attempt to split at the last whitespace before 200 characters
        cut_point = tts_str[:200].rsplit(' ', 1)
        # If there is a suitable place to split
        if len(cut_point) > 1 and len(cut_point[0]) > 0:
            return cut_point[0]
        else:
            # If no suitable whitespace is found, cut at 200 characters
            return tts_str[:200]
    else:
        # If the string is less than or equal to 200 characters, return it as is
        return tts_str

def push_tts(sp, polly_client, tts_str):
    # check if string is longer than 200 chars and cut it
    tts_str = cut_string(tts_str)

    # get tts file
    response = polly_client.synthesize_speech(VoiceId='Hans',
                                              OutputFormat='mp3',
                                              Text=tts_str)

    # Save the audio to a file
    file_name = 'tts.mp3'
    with open(file_name, 'wb') as file:
        file.write(response['AudioStream'].read())

    # lower volume so we can hear what is being said
    sp.volume(SPOTIFY_MUTE_VOLUME)

    # play tts file
    os.system("afplay tts.mp3")

    # set volume back
    sp.volume(SPOTIFY_MAX_VOLUME)

    os.remove("tts.mp3")

def push_donation(donor_name, amount, message, spotify_link):
    url = "https://api.saufen.neoxen.de/donations/"
    #url = "http://127.0.0.1:8000/donations/"

    if message:
        payload = json.dumps({
          "donor_name": str(donor_name),
          "amount": amount,
          "message": str(message)
        })
    elif spotify_link:
        payload = json.dumps({
          "donor_name": str(donor_name),
          "amount": amount,
          "spotify_link": str(spotify_link)
        })
    else:
        payload = json.dumps({
          "donor_name": str(donor_name),
          "amount": amount
        })

    headers = {
      'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)

    if response.status_code == 200:
        print("Successfully pushed donation.")
    else:
        print(f"Error pushing donation: {response}")


def clean_donation_amount(donation_amount_str):
    # Use a regular expression to find the numerical part
    # This pattern looks for numbers that may contain a comma as the decimal separator
    match = re.search(r"(\d+,\d+)", donation_amount_str)
    if match:
        # Replace comma with dot for conversion to float
        donation_amount = float(match.group().replace(",", "."))
    else:
        donation_amount = None

    if donation_amount is not None:
        return donation_amount
    else:
        return None

def scrape_mail(html_content):
    # Correct the HTML content format for parsing
    soup = BeautifulSoup(html_content.replace("=3D", "="), "html.parser")

    # Create a dictionary to store the results
    results = {
        "Gesamtbetrag:": None,
        "Wer sich beteiligt hat:": None,
        "Nachricht:": None
    }

    # Find the table by its ID
    cart_details_table = soup.find('table', {'id': 'cartDetails'})

    # Find all <td> elements with <b> tags (which contain the labels)
    td_elements = cart_details_table.find_all('td')
    for i in range(0, len(td_elements)-1, 2):  # Process pairs of <td> elements
        label_td = td_elements[i]
        value_td = td_elements[i+1]
        label_text = label_td.get_text(strip=True)
        value_text = value_td.get_text(strip=True)
        if label_text in results:
            # Decode HTML entities in value_text
            results[label_text] = BeautifulSoup(value_text, "html.parser").text

    return results


def get_email_body(service, user_id, msg_id):
    """Get the email body of a specific message, looking for HTML content."""
    try:
        message = (
            service.users()
            .messages()
            .get(userId=user_id, id=msg_id, format="full")
            .execute()
        )
        body = None

        # Handle both cases: multipart and non-multipart emails
        if "parts" in message["payload"]:
            for part in message["payload"]["parts"]:
                if part["mimeType"] == "text/html":
                    data = part["body"]["data"]
                    html_content = base64.urlsafe_b64decode(
                        data.encode("ASCII")
                    ).decode("utf-8")

                    # format to proper html
                    html_content = html_content.replace("=\n", "")
                    return html_content

        else:
            data = message["payload"]["body"]["data"]
            html_content = base64.urlsafe_b64decode(data.encode("ASCII")).decode(
                "utf-8"
            )

            # format to proper html
            html_content = html_content.replace("=\n", "")
            return html_content

    except HttpError as error:
        print(f"An error occurred: {error}")
    except KeyError as error:
        print(f"A KeyError occurred: {error}")
    return None


def main():
    """Continuously checks for new emails from service@paypal.de and handles our business logic"""
    creds = None
    if os.path.exists("google_credentials_cache.json"):
        creds = Credentials.from_authorized_user_file("google_credentials_cache.json", GOOGLE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "google_credentials.json", GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=8080)
        with open("google_credentials_cache.json", "w") as token:
            token.write(creds.to_json())

    sp = authenticate_spotify()

    # polly_client = authenticate_polly()

    service = build("gmail", "v1", credentials=creds)

    print("Monitoring for new emails from service@paypal.de")
    print(f"Minimum dono amount to trigger TTS: {MIN_TTS_AMOUNT}€")
    print(f"Minimum dono amount to add Spotify tracks: {MIN_SPOTIFY_AMOUNT}€")
    print(f"Minimum dono amount to skip Spotify tracks: {MIN_SPOTIFY_SKIP_AMOUNT}€")
    known_ids = set()  # Keeps track of emails that have been seen

    while True:
        try:
            # Check for new emails from service@paypal.de
            query = "from:service@paypal.de is:unread"
            results = service.users().messages().list(userId="me", q=query).execute()
            messages = results.get("messages", [])

            if messages:
                for message in messages:
                    if message["id"] not in known_ids:
                        print("-----------")
                        
                        # init spotify track empty
                        spotify_track = None

                        # Mark as known
                        known_ids.add(message["id"])

                        # get the email body
                        mail_body = get_email_body(service, "me", message["id"])

                        # scrape for donor_name, donation_amount, message
                        donation_spec = scrape_mail(mail_body)

                        # find the donor-name
                        donor_name = donation_spec["Wer sich beteiligt hat:"]

                        if not donor_name:
                            print("Didn't find donor name :(")
                            continue

                        print(f"Donor name: {donor_name}")

                        # check if the donation was higher than 1€
                        donation_amount = clean_donation_amount(donation_spec["Gesamtbetrag:"])

                        # skip if we cannot find donation amount
                        if not donation_amount:
                            print("Didn't find donation amount :(")
                            continue

                        print(f"Donation amount: {donation_amount}€")
                        
                        # fetch message
                        message = donation_spec["Nachricht:"]

                        # check if there's a message present
                        if message:
                            # first, check if someone bought something at the bar so we can skip tts
                            is_bar_transaction = check_bar_transaction(message)

                            # if it's not a bar transaction, check if it's a spotify track
                            if not is_bar_transaction:
                                spotify_track = find_spotify_url(message)

                            if is_bar_transaction:
                                print(f"Pretty sure this is a bar transaction: {message}")
                                push_donation(donor_name, donation_amount, None, None)
                                continue
                            elif spotify_track:
                                if donation_amount < MIN_SPOTIFY_AMOUNT:
                                    print(f"Donation doesn't meet minimal donation amount for Spotify")
                                    push_donation(donor_name, donation_amount, None, None)
                                    continue
                                else:
                                    print(f"New spotify track link found: {spotify_track}")
                                    add_track_to_queue(sp, spotify_track)
                                    songname = find_spotify_track_name(sp, spotify_track)
                                    if songname:
                                        print(f"Track name: {songname}")
                                        push_donation(donor_name, donation_amount, None, songname)
                                        continue
                                    else:
                                        print(f"Spotify URL found, but could not get songname. Queuing anyways.")
                                        push_donation(donor_name, donation_amount, None, None)
                                        continue
                            elif find_skip(message, donation_amount): # check if the user wants to skip the current song
                                print("Found skip...")
                                skip_track(sp)
                                push_donation(donor_name, donation_amount, message, None)
                                continue
                            else:
                                # if we cannot find a track name, push donation anyways
                                print(f"Message: {message}")
                                push_donation(donor_name, donation_amount, message, None)
                                continue

                            # if donation_amount < MIN_TTS_AMOUNT:
                            #     print(f"Donation doesn't meet minimal donation amount for TTS")
                            #     push_donation(donor_name, donation_amount, None, None)
                            #     continue
                            # else:
                            #     print(f"New tts message found: {message}")
                            #     push_donation(donor_name, donation_amount, message, None)
                            #     push_tts(sp, polly_client, message.replace(":",""))
                            #     continue
                        else:
                            # this catches all donos that did not provide a text or link
                            print("No spotify link / TTS text present")
                            push_donation(donor_name, donation_amount, None, None)

            time.sleep(REFRESH_TIME)  # Wait before checking again
        except KeyboardInterrupt:
            print("Program stopped by user.\n\nMARK MAILS AS READ BEFORE EXECUTING AGAIN!!!")
            exit(0)
        except Exception as e:
            print(f"Unexpected Error: {e}")

if __name__ == "__main__":
    print("Startup...")
    main()
