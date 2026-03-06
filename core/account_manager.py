import os
import json
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from config.constants import (
    CREDENTIALS_FILE,
    ACCOUNTS_DIR,
    SCOPES
)

class AccountManager:

    def __init__(self):
        os.makedirs(ACCOUNTS_DIR, exist_ok=True)
        self.current_account = None
        self.youtube = None

    def add_account(self):
        if not os.path.exists(CREDENTIALS_FILE):
            raise FileNotFoundError("credentials.json not found in auth folder.")

        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            SCOPES
        )

        creds = flow.run_local_server(port=0)
        youtube = build("youtube", "v3", credentials=creds)

        request = youtube.channels().list(
            part="snippet",
            mine=True
        )
        response = request.execute()

        if not response["items"]:
            raise Exception("No YouTube channel found.")

        channel_title = response["items"][0]["snippet"]["title"]
        safe_name = self._sanitize_name(channel_title)

        account_path = os.path.join(ACCOUNTS_DIR, safe_name)
        os.makedirs(account_path, exist_ok=True)

        token_path = os.path.join(account_path, "token.json")
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

        history_path = os.path.join(account_path, "history.json")
        if not os.path.exists(history_path):
            with open(history_path, "w") as f:
                json.dump([], f)

        logging.info(f"Account added: {channel_title}")

        self.current_account = safe_name
        self.youtube = youtube

        return safe_name

    def load_account(self, account_name):
        account_path = os.path.join(ACCOUNTS_DIR, account_name)
        token_path = os.path.join(account_path, "token.json")

        if not os.path.exists(token_path):
            raise FileNotFoundError("token.json not found for selected account.")

        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        self.youtube = build("youtube", "v3", credentials=creds)
        self.current_account = account_name

        logging.info(f"Loaded account: {account_name}")

        return self.youtube

    def list_accounts(self):
        if not os.path.exists(ACCOUNTS_DIR):
            return []

        return [
            name for name in os.listdir(ACCOUNTS_DIR)
            if os.path.isdir(os.path.join(ACCOUNTS_DIR, name))
        ]

    def get_current_account(self):
        return self.current_account

    def _sanitize_name(self, name):
        return "".join(c for c in name if c.isalnum() or c in (" ", "_", "-")).strip()