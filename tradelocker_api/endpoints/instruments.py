import logging
from functools import lru_cache
from tradelocker_api.endpoints.auth import TradeLockerAuth
from tradelocker_api.api_client import ApiClient

logger = logging.getLogger(__name__)


class TradeLockerInstruments(ApiClient):
    """
    Client for TradeLocker instruments API with improved caching and async support
    """

    def __init__(self, auth: TradeLockerAuth):
        super().__init__(auth)
        # In-memory cache for instrument lookups
        self._instrument_cache = {}

    # Synchronous methods (for backward compatibility)

    def get_instruments(self, account_id: int, acc_num: int):
        """
        Fetch all available instruments for the account.
        Uses caching to avoid excessive API calls.
        """
        try:
            headers = {"accNum": str(acc_num)}
            # Cache instruments for 30 minutes (1800 seconds)
            result = self.request(
                'GET',
                f'trade/accounts/{account_id}/instruments',
                headers=headers,
                cache_ttl=1800
            )

            # Extract instruments from response
            instruments = result.get("d", {}).get("instruments", [])

            if not instruments:
                logger.warning("No instruments found.")
                return None

            return instruments

        except Exception as e:
            logger.error(f"Failed to fetch instruments: {e}")
            return None

    @lru_cache(maxsize=100)
    def get_instrument_by_name(self, account_id: int, acc_num: int, name: str):
        """
        Find an instrument by its name and return the full instrument data.
        Uses function-level caching for frequently accessed instruments.
        """
        cache_key = f"{account_id}:{acc_num}:{name}"

        # Check in-memory cache first
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]

        # Fetch instruments if needed
        instruments = self.get_instruments(account_id, acc_num)
        if instruments:
            for instrument in instruments:
                if instrument.get('name') == name:
                    # Cache the result
                    self._instrument_cache[cache_key] = instrument
                    return instrument
            logger.warning(f"Instrument '{name}' not found.")
        return None

    def get_instrument_by_id(self, account_id: int, acc_num: int, instrument_id: int):
        """
        Find an instrument by its ID and return the full instrument data.
        Uses function-level caching.
        """
        cache_key = f"{account_id}:{acc_num}:id:{instrument_id}"

        # Check in-memory cache first
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]

        # Fetch instruments if needed
        instruments = self.get_instruments(account_id, acc_num)

        if instruments is None:
            logger.error(f"Failed to retrieve instruments for account {account_id}, account number {acc_num}.")
            return None

        # Find instrument by ID
        for instrument in instruments:
            current_instrument_id = int(instrument.get('tradableInstrumentId', -1))
            if current_instrument_id == int(instrument_id):
                # Cache the result
                self._instrument_cache[cache_key] = instrument
                return instrument

        logger.warning(f"Instrument with ID {instrument_id} not found.")
        return None

    # Asynchronous methods (for new code)

    async def get_instruments_async(self, account_id: int, acc_num: int):
        """
        Fetch all available instruments for the account - async version.
        """
        try:
            headers = {"accNum": str(acc_num)}
            # Cache instruments for 30 minutes (1800 seconds)
            result = await self.request_async(
                'GET',
                f'trade/accounts/{account_id}/instruments',
                headers=headers,
                cache_ttl=1800
            )

            # Extract instruments from response
            instruments = result.get("d", {}).get("instruments", [])

            if not instruments:
                logger.warning("No instruments found.")
                return None

            return instruments

        except Exception as e:
            logger.error(f"Failed to fetch instruments: {e}")
            return None

    async def get_instrument_by_name_async(self, account_id: int, acc_num: int, name: str):
        """
        Find an instrument by its name - async version.
        """
        cache_key = f"{account_id}:{acc_num}:{name}"

        # Check in-memory cache first
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]

        # Fetch instruments if needed
        instruments = await self.get_instruments_async(account_id, acc_num)
        if instruments:
            for instrument in instruments:
                if instrument.get('name') == name:
                    # Cache the result
                    self._instrument_cache[cache_key] = instrument
                    return instrument
            logger.warning(f"Instrument '{name}' not found.")
        return None

    async def get_instrument_by_id_async(self, account_id: int, acc_num: int, instrument_id: int):
        """
        Find an instrument by its ID - async version.
        """
        cache_key = f"{account_id}:{acc_num}:id:{instrument_id}"

        # Check in-memory cache first
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]

        # Fetch instruments if needed
        instruments = await self.get_instruments_async(account_id, acc_num)

        if instruments is None:
            logger.error(f"Failed to retrieve instruments for account {account_id}, account number {acc_num}.")
            return None

        # Find instrument by ID
        for instrument in instruments:
            current_instrument_id = int(instrument.get('tradableInstrumentId', -1))
            if current_instrument_id == int(instrument_id):
                # Cache the result
                self._instrument_cache[cache_key] = instrument
                return instrument

        logger.warning(f"Instrument with ID {instrument_id} not found.")
        return None

    def clear_cache(self):
        """Clear all instrument caches"""
        self._instrument_cache.clear()
        # Clear lru_cache for get_instrument_by_name
        self.get_instrument_by_name.cache_clear()
        # Also clear the parent class cache
        super().clear_cache()