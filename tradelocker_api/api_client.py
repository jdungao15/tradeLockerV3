import time
import asyncio
import aiohttp
import logging
import requests

from tradelocker_api.endpoints.auth import TradeLockerAuth

logger = logging.getLogger(__name__)


class ApiClient:
    """
    Base API client with caching, rate limiting, and circuit breaker patterns.
    Provides both synchronous and asynchronous methods for API access.
    """

    def __init__(self, auth: TradeLockerAuth, default_timeout=10):
        self.auth = auth
        self.base_url = auth.base_url
        self.default_timeout = default_timeout
        self._session = None
        self._rate_limits = {}  # Track rate limits per endpoint
        self._circuit_states = {}  # Track circuit breaker states
        self._cache = {}  # Simple time-based cache
        self._cache_ttl = {}  # TTL for each cached item

    # Circuit breaker methods

    def _record_success(self, endpoint):
        """Record a successful API call"""
        if endpoint in self._circuit_states:
            state = self._circuit_states[endpoint]
            if state['status'] in ['OPEN', 'HALF-OPEN']:
                logger.info(f"Circuit for {endpoint} is now CLOSED after successful call")
                self._circuit_states[endpoint] = {
                    'status': 'CLOSED',
                    'failures': 0,
                    'last_failure': 0
                }

    def _record_failure(self, endpoint):
        """Record a failed API call"""
        if endpoint not in self._circuit_states:
            self._circuit_states[endpoint] = {
                'status': 'CLOSED',
                'failures': 0,
                'last_failure': 0
            }

        state = self._circuit_states[endpoint]
        state['failures'] += 1
        state['last_failure'] = time.time()

        # Open circuit after 5 consecutive failures
        if state['status'] == 'CLOSED' and state['failures'] >= 5:
            state['status'] = 'OPEN'
            logger.warning(f"Circuit OPEN for {endpoint} after {state['failures']} failures")

    def _can_execute(self, endpoint):
        """Check if request can be executed based on circuit state"""
        if endpoint not in self._circuit_states:
            return True

        state = self._circuit_states[endpoint]
        now = time.time()

        if state['status'] == 'CLOSED':
            return True

        elif state['status'] == 'OPEN':
            # Try again after 60 seconds
            if now - state['last_failure'] > 60:
                state['status'] = 'HALF-OPEN'
                logger.info(f"Circuit for {endpoint} moving to HALF-OPEN")
                return True
            return False

        elif state['status'] == 'HALF-OPEN':
            # In half-open, allow one request every 30 seconds
            return (now - state['last_failure']) > 30

        return True

    # Asynchronous session management

    async def ensure_session(self):
        """Ensure aiohttp session exists"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"}
            )
        return self._session

    async def close(self):
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # Synchronous request method (for backward compatibility)

    def request(self, method, endpoint, headers=None, params=None, json=None,
                data=None, cache_ttl=0, retry_count=3):
        """Make a synchronous API request with caching and circuit breaker"""
        # Check circuit breaker
        if not self._can_execute(endpoint):
            logger.warning(f"Circuit breaker open for {endpoint}, request blocked")
            raise Exception(f"Service unavailable: {endpoint}")

        # Generate cache key if caching is enabled
        cache_key = None
        if cache_ttl > 0 and method.lower() == 'get':
            cache_key = f"{method}:{endpoint}:{str(params)}:{str(json)}"
            # Check cache
            if cache_key in self._cache:
                if time.time() < self._cache_ttl.get(cache_key, 0):
                    return self._cache[cache_key]

        # Prepare request
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if headers is None:
            headers = {}

        # Add authorization header
        headers["Authorization"] = f"Bearer {self.auth.get_access_token()}"

        # Execute with retry logic
        for attempt in range(retry_count):
            try:
                response = requests.request(
                    method, url, headers=headers, params=params,
                    json=json, data=data, timeout=self.default_timeout
                )

                # Handle 401 (Unauthorized)
                if response.status_code == 401:
                    logger.info("Token expired, refreshing")
                    headers["Authorization"] = f"Bearer {self.auth.refresh_auth_token()}"
                    continue  # Retry with new token

                # Raise for status
                response.raise_for_status()

                # Parse response
                result = response.json()

                # Cache result if enabled
                if cache_key is not None and cache_ttl > 0:
                    self._cache[cache_key] = result
                    self._cache_ttl[cache_key] = time.time() + cache_ttl

                # Record success for circuit breaker
                self._record_success(endpoint)

                return result

            except Exception as e:
                # Handle network errors
                if attempt == retry_count - 1:  # Last attempt
                    # Record failure
                    self._record_failure(endpoint)
                    logger.error(f"Request to {endpoint} failed after {retry_count} attempts: {e}")
                    raise

                # Exponential backoff
                wait_time = 0.5 * (2 ** attempt)
                logger.warning(f"Request failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

    # Asynchronous request method (for new code)

    async def request_async(self, method, endpoint, headers=None, params=None, json=None,
                            data=None, cache_ttl=0, retry_count=3):
        """Make an asynchronous API request with caching, rate limiting and circuit breaker"""
        # Check circuit breaker
        if not self._can_execute(endpoint):
            logger.warning(f"Circuit breaker open for {endpoint}, request blocked")
            raise Exception(f"Service unavailable: {endpoint}")

        # Generate cache key if caching is enabled
        cache_key = None
        if cache_ttl > 0 and method.lower() == 'get':
            cache_key = f"{method}:{endpoint}:{str(params)}:{str(json)}"
            # Check cache
            if cache_key in self._cache:
                if time.time() < self._cache_ttl.get(cache_key, 0):
                    return self._cache[cache_key]

        # Prepare request
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if headers is None:
            headers = {}

        # Add authentication
        headers["Authorization"] = f"Bearer {await self.auth.get_access_token_async()}"

        # Ensure we have a session
        session = await self.ensure_session()

        # Execute request with retry logic
        for attempt in range(retry_count):
            try:
                async with session.request(
                        method, url, headers=headers, params=params, json=json,
                        data=data, timeout=self.default_timeout
                ) as response:
                    # Handle 401 (Unauthorized)
                    if response.status == 401:
                        logger.info("Token expired, refreshing")
                        await self.auth.refresh_auth_token_async()
                        headers["Authorization"] = f"Bearer {await self.auth.get_access_token_async()}"
                        continue  # Retry with new token

                    # Raise for other HTTP errors
                    response.raise_for_status()

                    # Parse response
                    result = await response.json()

                    # Cache the result if enabled
                    if cache_key is not None and cache_ttl > 0:
                        self._cache[cache_key] = result
                        self._cache_ttl[cache_key] = time.time() + cache_ttl

                    # Record success for circuit breaker
                    self._record_success(endpoint)

                    return result

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == retry_count - 1:  # Last attempt
                    # Record failure for circuit breaker
                    self._record_failure(endpoint)
                    logger.error(f"Request to {endpoint} failed after {retry_count} attempts: {e}")
                    raise

                # Exponential backoff
                wait_time = 0.5 * (2 ** attempt)
                logger.warning(f"Request failed, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)

    # Cache management

    def clear_cache(self):
        """Clear the entire cache"""
        self._cache.clear()
        self._cache_ttl.clear()

    def clear_cache_for_endpoint(self, endpoint):
        """Clear cache for a specific endpoint"""
        keys_to_remove = []
        for key in self._cache.keys():
            if endpoint in key:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._cache[key]
            if key in self._cache_ttl:
                del self._cache_ttl[key]