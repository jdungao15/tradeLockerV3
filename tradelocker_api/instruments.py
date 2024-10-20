import requests
from tradelocker_api.auth import TradeLockerAuth


class TradeLockerInstruments:
    def __init__(self, auth: TradeLockerAuth):
        self.auth = auth
        self.base_url = auth.base_url

    def get_instruments(self, account_id: int, acc_num: int):
        """
        Fetch all available instruments for the account.
        """
        url = f"{self.base_url}/trade/accounts/{account_id}/instruments"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num)  # Add accNum in headers as required
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            # Access the instruments data under 'd' key
            instruments = response.json().get("d", {}).get("instruments", [])

            if not instruments:
                print("No instruments found.")
                return None

            return instruments

        except requests.exceptions.HTTPError as e:
            # Check if the error is due to token expiration (e.g., 401 Unauthorized)
            if response.status_code == 401:
                print("Token expired, from Instrument.py")
                print("Token expired, refreshing token...")
                refresh_token = self.auth.refresh_auth_token()  # Refresh the token

                # Retry the request with the new token
                headers["Authorization"] = f"Bearer {refresh_token}"
                try:
                    response = requests.get(url, headers=headers)
                    response.raise_for_status()

                    # Access the instruments data under 'd' key
                    instruments = response.json().get("d", {}).get("instruments", [])

                    if not instruments:
                        print("No instruments found after retry.")
                        return None
                    print("Succesfully, fetched instruments with new token refresh.")
                    return instruments
                except requests.exceptions.RequestException as retry_error:
                    print(f"Failed to fetch instruments after token refresh: {retry_error}")
                    return None
            else:
                print(f"Failed to fetch instruments: {e}")
                return None

    def get_instrument_by_name(self, account_id: int, acc_num: int, name: str):
        """
        Find an instrument by its name and return the full instrument data.
        """
        instruments = self.get_instruments(account_id, acc_num)
        if instruments:
            for instrument in instruments:
                if instrument.get('name') == name:
                    return instrument  # Return the entire instrument data
            print(f"Instrument '{name}' not found.")
        return None


