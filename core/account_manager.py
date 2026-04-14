import os
import json
import logging
import shutil
import base64
import hashlib
import uuid
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from cryptography.fernet import Fernet
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
        self._fernet = None

    def _get_fernet(self):
        """Lazy-load the hardware-bound Fernet instance."""
        if self._fernet is None:
            # Derive a key from hardware ID (UUID node)
            node = str(uuid.getnode()).encode()
            key = hashlib.sha256(node).digest()
            fernet_key = base64.urlsafe_b64encode(key)
            self._fernet = Fernet(fernet_key)
        return self._fernet

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
        
        # Encrypt token data before saving
        raw_json = creds.to_json()
        token_data = raw_json.encode('utf-8') if isinstance(raw_json, str) else raw_json
        encrypted_token = self._get_fernet().encrypt(token_data)
        
        with open(token_path, "wb") as token_file:
            token_file.write(encrypted_token)
        self._secure_token_file(token_path)

        history_path = os.path.join(account_path, "history.json")
        if not os.path.exists(history_path):
            with open(history_path, "w") as f:
                json.dump([], f)

        logging.info(f"Account added and encrypted: {channel_title}")

        self.current_account = safe_name
        self.youtube = youtube

        return safe_name

    def load_account(self, account_name):
        account_path = os.path.join(ACCOUNTS_DIR, account_name)
        token_path = os.path.join(account_path, "token.json")

        if not os.path.exists(token_path):
            raise FileNotFoundError("token.json not found for selected account.")

        # Read and decrypt token
        with open(token_path, "rb") as token_file:
            encrypted_token = token_file.read()
        
        try:
            # Try to decrypt (modern encrypted format)
            decrypted_token = self._get_fernet().decrypt(encrypted_token)
            token_dict = json.loads(decrypted_token.decode('utf-8'))
            creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
        except Exception:
            # Fallback for old plain-text tokens (auto-upgrade them)
            logging.info("Legacy token detected. Upgrading to encrypted format...")
            with open(token_path, "r", encoding="utf-8") as f:
                raw_json = f.read()
                creds = Credentials.from_authorized_user_info(json.loads(raw_json), SCOPES)
            
            # Re-save in encrypted format
            self.save_creds(account_name, creds)

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.save_creds(account_name, creds)
        else:
            self._secure_token_file(token_path)

        self.youtube = build("youtube", "v3", credentials=creds)
        self.current_account = account_name

        logging.info(f"Loaded account: {account_name}")

        return self.youtube

    def save_creds(self, account_name, creds):
        """Helper to safely encrypt and save credentials."""
        account_path = os.path.join(ACCOUNTS_DIR, account_name)
        token_path = os.path.join(account_path, "token.json")
        
        # Ensure it is bytes
        raw_data = creds.to_json()
        if isinstance(raw_data, str):
            token_data = raw_data.encode('utf-8')
        else:
            token_data = raw_data
            
        encrypted_token = self._get_fernet().encrypt(token_data)
        
        with open(token_path, "wb") as token_file:
            token_file.write(encrypted_token)
        self._secure_token_file(token_path)

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
