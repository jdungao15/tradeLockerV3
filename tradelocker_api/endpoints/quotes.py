import logging
from tradelocker_api.endpoints.auth import TradeLockerAuth
from tradelocker_api.api_client import ApiClient
from tradelocker_api.endpoints.instruments import TradeLockerInstruments

logger = logging.getLogger(__name__)


class TradeLockerQuotes(ApiClient):
    """
    Client for TradeLocker quotes API with improved caching and async support
    """

    def __init__(self, auth: TradeLockerAuth):
        super().__init__(auth)
        # We'll create our own instruments client to avoid circular imports
        self.instrument_client = TradeLockerInstruments(auth)
        # Cache to store route IDs by instrument
        self._route_cache = {}

    # Synchronous methods (for backward compatibility)

    def get_quote(self, account: dict, instrument_name: str):
        """
        Fetch the current price (quote) of the instrument.
        Uses caching for instrument lookups but not for quotes (which change frequently).
        """
        try:
            acc_num = account['accNum']
            account_id = account['id']

            # Use cached route ID if available
            route_key = f"{account_id}:{acc_num}:{instrument_name}"
            route_info = self._route_cache.get(route_key)

            if not route_info:
                # Get instrument details by name
                instrument_data = self.instrument_client.get_instrument_by_name(
                    account_id=account_id,
                    acc_num=acc_num,
                    name=instrument_name
                )

                if not instrument_data:
                    logger.warning(f"Instrument {instrument_name} not found.")
                    return None

                # Find the INFO route
                info_route = next((route['id'] for route in instrument_data['routes'] if route['type'] == 'INFO'), None)

                if not info_route:
                    logger.warning(f"INFO route not found for instrument {instrument_name}.")
                    return None

                tradable_instrument_id = instrument_data['tradableInstrumentId']

                # Cache the route info
                self._route_cache[route_key] = {
                    'route_id': info_route,
                    'instrument_id': tradable_instrument_id
                }
            else:
                info_route = route_info['route_id']
                tradable_instrument_id = route_info['instrument_id']

            # Prepare and make API request
            headers = {"accNum": str(acc_num)}
            params = {
                "routeId": info_route,
                "tradableInstrumentId": tradable_instrument_id
            }

            # Quotes are never cached as they change frequently
            return self.request('GET', 'trade/quotes', headers=headers, params=params)

        except Exception as e:
            logger.error(f"Error while fetching quote: {e}")
            return None

    # Asynchronous methods (for new code)

    async def get_quote_async(self, account: dict, instrument_name: str):
        """
        Fetch the current price (quote) of the instrument - async version.
        """
        try:
            acc_num = account['accNum']
            account_id = account['id']

            # Use cached route ID if available
            route_key = f"{account_id}:{acc_num}:{instrument_name}"
            route_info = self._route_cache.get(route_key)

            if not route_info:
                # Get instrument details by name
                instrument_data = await self.instrument_client.get_instrument_by_name_async(
                    account_id=account_id,
                    acc_num=acc_num,
                    name=instrument_name
                )

                if not instrument_data:
                    logger.warning(f"Instrument {instrument_name} not found.")
                    return None

                # Find the INFO route
                info_route = next((route['id'] for route in instrument_data['routes'] if route['type'] == 'INFO'), None)

                if not info_route:
                    logger.warning(f"INFO route not found for instrument {instrument_name}.")
                    return None

                tradable_instrument_id = instrument_data['tradableInstrumentId']

                # Cache the route info
                self._route_cache[route_key] = {
                    'route_id': info_route,
                    'instrument_id': tradable_instrument_id
                }
            else:
                info_route = route_info['route_id']
                tradable_instrument_id = route_info['instrument_id']

            # Prepare and make API request
            headers = {"accNum": str(acc_num)}
            params = {
                "routeId": info_route,
                "tradableInstrumentId": tradable_instrument_id
            }

            # Quotes are never cached as they change frequently
            return await self.request_async('GET', 'trade/quotes', headers=headers, params=params)

        except Exception as e:
            logger.error(f"Error while fetching quote: {e}")
            return None

    async def get_quotes_batch_async(self, account: dict, instrument_names: list):
        """
        Fetch quotes for multiple instruments in parallel - async version.
        """
        import asyncio

        try:
            tasks = [self.get_quote_async(account, name) for name in instrument_names]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            quotes = {}
            for i, result in enumerate(results):
                instrument_name = instrument_names[i]
                if isinstance(result, Exception):
                    logger.error(f"Error fetching quote for {instrument_name}: {result}")
                    quotes[instrument_name] = None
                else:
                    quotes[instrument_name] = result

            return quotes
        except Exception as e:
            logger.error(f"Error fetching batch quotes: {e}")
            return {}