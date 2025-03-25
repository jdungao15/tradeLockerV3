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
        Enhanced to handle different instrument naming conventions.
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

                    # ENHANCED FALLBACK: Try to find by alternate names if this is a known instrument
                    from utils.instrument_utils import identify_instrument_group

                    # Check if this is a known instrument type with alternate names
                    group_name, alternate_names = identify_instrument_group(instrument_name)

                    if group_name and alternate_names:
                        logger.info(f"Trying alternate names for {instrument_name}: {alternate_names}")

                        # Try each alternate name
                        for alt_name in alternate_names:
                            if alt_name == instrument_name:
                                continue  # Skip the original name

                            alt_instrument = await self.instrument_client.get_instrument_by_name_async(
                                account_id=account_id,
                                acc_num=acc_num,
                                name=alt_name
                            )

                            if alt_instrument:
                                logger.info(f"Found instrument using alternate name: {alt_name}")
                                instrument_data = alt_instrument
                                break

                    # If still not found after trying alternates
                    if not instrument_data:
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
        Enhanced to handle different instrument naming conventions.
        """
        import asyncio

        try:
            tasks = []
            for name in instrument_names:
                # Create a task for each instrument
                task = self.get_quote_async(account, name)
                tasks.append((name, asyncio.create_task(task)))

            # Process results
            quotes = {}
            for name, task in tasks:
                try:
                    result = await task
                    quotes[name] = result
                except Exception as e:
                    logger.error(f"Error fetching quote for {name}: {e}")
                    quotes[name] = None

            return quotes
        except Exception as e:
            logger.error(f"Error fetching batch quotes: {e}")
            return {}