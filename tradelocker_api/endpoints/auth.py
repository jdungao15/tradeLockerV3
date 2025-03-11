import os
import time
import asyncio
import aiohttp
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class TradeLockerAuth:
    """
    Authentication client with both synchronous and asynchronous methods
    for backward compatibility during migration
    """

    def __init__(self):
        self.base_url = os.getenv("TRADELOCKER_API_URL")
        self.email = os.getenv("TRADELOCKER_EMAIL")
        self.password = os.getenv("TRADELOCKER_PASSWORD")
        self.server = os.getenv("TRADELOCKER_SERVER")

        self.access_token = None
        self.refresh_token = None
        self.token_expiry = 0
        self._token_lock = asyncio.Lock()  # Lock for thread safety
        self._session = None
        self._token_renewal_task = None

    # Synchronous methods (for backward compatibility)

    def authenticate(self):
        """
        Authenticate using username, password, and server - synchronous method.
        """
        try:
            url = f"{self.base_url}/auth/jwt/token"
            payload = {
                "email": self.email,
                "password": self.password,
                "server": self.server
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            self.access_token = data['accessToken']
            self.refresh_token = data['refreshToken']
            self.token_expiry = time.time() + 3600  # Assuming 1 hour validity

            # Start async token renewal if in an event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.start_token_renewal())
            except RuntimeError:
                # No event loop, running in sync context
                pass

            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication failed: {e}")
            return None

    def refresh_auth_token(self):
        """
        Refresh the authentication tokens - synchronous method.
        """
        try:
            url = f"{self.base_url}/auth/jwt/refresh"
            payload = {"refreshToken": self.refresh_token}
            response = requests.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            self.access_token = data['accessToken']
            self.refresh_token = data['refreshToken']
            self.token_expiry = time.time() + 3600  # Assuming 1 hour validity

            return self.access_token
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to refresh token: {e}")
            # Attempt re-authentication if refresh fails
            return self.authenticate()

    def get_access_token(self):
        """
        Ensure access token is valid, refreshing if necessary - synchronous method.
        """
        now = time.time()
        # Refresh token if it will expire in less than 5 minutes
        if not self.access_token or now > self.token_expiry - 300:
            if not self.refresh_token:
                self.authenticate()
            else:
                self.refresh_auth_token()
        return self.access_token

    # Asynchronous methods (for new code)

    async def ensure_session(self):
        """Ensure aiohttp session exists"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"}
            )
        return self._session

    async def start_token_renewal(self):
        """Start background task to renew token automatically"""
        if self._token_renewal_task is None or self._token_renewal_task.done():
            self._token_renewal_task = asyncio.create_task(self._token_renewal_loop())

    async def _token_renewal_loop(self):
        """Background task to renew token before it expires"""
        while True:
            try:
                # Check if token expires in less than 5 minutes
                if self.access_token and time.time() > self.token_expiry - 300:
                    logger.debug("Proactively renewing auth token")
                    await self.refresh_auth_token_async()

                # Sleep for 60 seconds before checking again
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in token renewal: {e}")
                await asyncio.sleep(60)  # Sleep and retry

    async def authenticate_async(self):
        """Authenticate asynchronously"""
        async with self._token_lock:  # Prevent concurrent auth attempts
            if self.access_token and time.time() < self.token_expiry - 300:
                return {"accessToken": self.access_token, "refreshToken": self.refresh_token}

            try:
                session = await self.ensure_session()
                url = f"{self.base_url}/auth/jwt/token"
                payload = {
                    "email": self.email,
                    "password": self.password,
                    "server": self.server
                }

                async with session.post(url, json=payload) as response:
                    response.raise_for_status()
                    data = await response.json()

                    self.access_token = data.get('accessToken')
                    self.refresh_token = data.get('refreshToken')

                    # Assuming token expires in 1 hour
                    self.token_expiry = time.time() + 3600

                    # Start token renewal in the background
                    await self.start_token_renewal()

                    return data
            except Exception as e:
                logger.error(f"Authentication failed: {e}")
                raise

    async def refresh_auth_token_async(self):
        """Refresh authentication token asynchronously"""
        async with self._token_lock:  # Prevent concurrent refresh attempts
            try:
                # Skip if we have a fresh token
                if self.access_token and time.time() < self.token_expiry - 300:
                    return self.access_token

                # Ensure we have a refresh token
                if not self.refresh_token:
                    return await self.authenticate_async()

                session = await self.ensure_session()
                url = f"{self.base_url}/auth/jwt/refresh"
                payload = {"refreshToken": self.refresh_token}

                async with session.post(url, json=payload) as response:
                    response.raise_for_status()
                    data = await response.json()

                    self.access_token = data.get('accessToken')
                    self.refresh_token = data.get('refreshToken')

                    # Update expiry time
                    self.token_expiry = time.time() + 3600

                    return self.access_token
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                # If refresh fails, try full re-authentication
                return await self.authenticate_async()

    async def get_access_token_async(self):
        """Get a valid access token, authenticating if necessary - async method"""
        if not self.access_token or time.time() > self.token_expiry - 300:
            if not self.refresh_token:
                await self.authenticate_async()
            else:
                await self.refresh_auth_token_async()
        return self.access_token

    async def close(self):
        """Close the session and cleanup"""
        if self._token_renewal_task and not self._token_renewal_task.done():
            self._token_renewal_task.cancel()
            try:
                await self._token_renewal_task
            except asyncio.CancelledError:
                pass

        if self._session and not self._session.closed:
            await self._session.close()