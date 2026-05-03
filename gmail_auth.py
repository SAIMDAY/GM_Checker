import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    creds = None
    
    # Load existing credentials if available
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # If credentials are invalid or expired, refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the new credentials
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    # Build Gmail service
    service = build("gmail", "v1", credentials=creds)

    # Test by fetching recent inbox messages
    results = service.users().messages().list(
        userId="me", 
        labelIds=["INBOX"], 
        maxResults=5
    ).execute()

    messages = results.get("messages", [])

    if messages:
        print(f"Found {len(messages)} messages. Gmail API is working!")
    else:
        print("No messages found, but authentication worked.")

    print("\n=== NEXT STEP ===")
    print("Now open token.json and copy the 'refresh_token' value.")
    print("You'll need it for the Render environment variable: GMAIL_REFRESH_TOKEN")


if __name__ == "__main__":
    main()
