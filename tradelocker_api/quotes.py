import requests
from tradelocker_api.auth import TradeLockerAuth
from tradelocker_api.instruments import TradeLockerInstruments


class TradeLockerQuotes:
    def __init__(self, auth: TradeLockerAuth):
        self.auth = auth
        self.base_url = auth.base_url
        self.instrument_client = TradeLockerInstruments(auth)

    def get_quote(self, account: dict, instrument_name: str):
        """
        Fetch the current price (quote) of the instrument using the account and instrument name.
        :param account: Account details (includes account ID, account number, etc.)
        :param instrument_name: Name of the instrument (e.g., 'XAUUSD')
        :return: JSON response with the quote details or None in case of failure.
        """
        acc_num = account['accNum']
        account_id = account['id']

        # Get instrument details by name
        instrument_data = self.instrument_client.get_instrument_by_name(account_id=account_id, acc_num=acc_num,
                                                                        name=instrument_name)

        if not instrument_data:
            print(f"Instrument {instrument_name} not found.")
            return None

        # Find the INFO route (instead of TRADE route)
        info_route = next((route['id'] for route in instrument_data['routes'] if route['type'] == 'INFO'), None)

        if not info_route:
            print(f"INFO route not found for instrument {instrument_name}.")
            return None

        tradable_instrument_id = instrument_data['tradableInstrumentId']  # Instrument id

        # Prepare API request
        url = f"{self.base_url}/trade/quotes"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num)
        }
        params = {
            "routeId": info_route,  # Use the INFO route ID here
            "tradableInstrumentId": tradable_instrument_id
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            if response.status_code == 401:
                print("Token expired, refreshing token...")
                refresh_token = self.auth.refresh_auth_token()

                # Retry with the new token
                headers["Authorization"] = f"Bearer {refresh_token}"
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                return response.json()

            print(f"Failed to fetch quote: {e}")
            return None

        except requests.exceptions.RequestException as e:
            print(f"Error while fetching quote: {e}")
            return None

