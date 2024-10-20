import os
import requests
from dotenv import load_dotenv

load_dotenv()


class TradeLockerAuth:
    def __init__(self):
        self.base_url = os.getenv("TRADELOCKER_API_URL")
        self.username = os.getenv("TRADELOCKER_USERNAME")
        self.password = os.getenv("TRADELOCKER_PASSWORD")
        self.server = os.getenv("TRADELOCKER_SERVER")
        self.access_token = None
        self.refresh_token = None

    def authenticate(self):
        """
        Authenticate using username, password, and server.
        Retrieves the access and refresh tokens.
        """
        try:
            url = f"{self.base_url}/auth/jwt/token"
            payload = {
                "email": self.username,
                "password": self.password,
                "server": self.server
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()  # Raise an error for bad responses
            data = response.json()

            self.access_token = data['accessToken']
            self.refresh_token = data['refreshToken']
            return data
        except requests.exceptions.RequestException as e:
            print(f"Authentication failed: {e}")
            return None

    def refresh_auth_token(self):
        """
        Refresh the authentication tokens.
        """
        try:
            url = f"{self.base_url}/auth/jwt/refresh"
            payload = {"refreshToken": self.refresh_token}
            response = requests.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            self.access_token = data['accessToken']
            self.refresh_token = data['refreshToken']

            return self.access_token
        except requests.exceptions.RequestException as e:
            print(f"Failed to refresh token: {e}")
            # Attempt re-authentication if refresh fails
            return self.authenticate()

    def get_access_token(self):
        """
        Ensure the access token is valid, refreshing it if necessary.
        """
        if not self.access_token:
            self.authenticate()
        return self.access_token
