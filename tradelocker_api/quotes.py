import requests
from tradelocker_api.auth import TradeLockerAuth


class TradeLockerQuotes:
    def __init__(self, auth: TradeLockerAuth):
        self.auth = auth
        self.base_url = auth.base_url

    def get_quote(self, acc_num: int, route_id: int, tradable_instrument_id: int):
        """
        Fetch the current price (quote) of the instrument using the specified parameters.
        :param acc_num: Account number (required header)
        :param route_id: Route identifier (required query parameter)
        :param tradable_instrument_id: Tradable instrument identifier (required query parameter)
        :return: JSON response with the quote details or None in case of failure.
        """
        url = f"{self.base_url}/trade/quotes"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num)
        }
        params = {
            "routeId": route_id,
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
