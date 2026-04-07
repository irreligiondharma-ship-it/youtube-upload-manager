import os
import json
import logging
import shutil
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
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

    def _secure_token_file(self, token_path):
        try:
            os.chmod(token_path, 0o600)
        except Exception as err:
            logging.warning("Could not restrict token file permissions: %s", err)

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
            raise RuntimeError("No YouTube channel found.")

        channel_title = response["items"][0]["snippet"]["title"]
        channel_id = response["items"][0]["id"]
        safe_name = self._sanitize_name(channel_title, channel_id)

        account_path = os.path.join(ACCOUNTS_DIR, safe_name)
        os.makedirs(account_path, exist_ok=True)

        token_path = os.path.join(account_path, "token.json")
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())
        self._secure_token_file(token_path)

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
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())
            self._secure_token_file(token_path)
        else:
            self._secure_token_file(token_path)

        self.youtube = build("youtube", "v3", credentials=creds)
        self.current_account = account_name

        logging.info(f"Loaded account: {account_name}")

        return self.youtube

    def remove_account(self, account_name):
        account_path = os.path.join(ACCOUNTS_DIR, account_name)
        if not os.path.exists(account_path):
            raise FileNotFoundError("Account folder not found.")
        shutil.rmtree(account_path)
        if self.current_account == account_name:
            self.current_account = None
            self.youtube = None

    def validate_account(self, account_name):
        youtube = self.load_account(account_name)
        request = youtube.channels().list(part="snippet", mine=True)
        response = request.execute()
        if not response.get("items"):
            raise RuntimeError("No YouTube channel found for this account.")
        return True

    def list_accounts(self):
        if not os.path.exists(ACCOUNTS_DIR):
            return []

        return [
            name for name in os.listdir(ACCOUNTS_DIR)
            if os.path.isdir(os.path.join(ACCOUNTS_DIR, name))
        ]

    def get_current_account(self):
        return self.current_account

    def _sanitize_name(self, name, channel_id=None):
        base = "".join(c for c in name if c.isalnum() or c in (" ", "_", "-")).strip()
        if channel_id:
            return f"{base}__{channel_id}"
        return base
