import requests
from tradelocker_api.endpoints.auth import TradeLockerAuth

class TradeLockerConfig:
    def __init__(self, auth: TradeLockerAuth):
        self.auth = auth
        self.base_url = auth.base_url

    def get_config(self, acc_num: int):
        """
        Retrieve the trade configuration for the specified account.
        """
        url = f"{self.base_url}/trade/config"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num)  # Required by the API
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            config = response.json()
            print(f"Trade configuration for account number {acc_num}: {config}")
            return config
        except requests.exceptions.HTTPError as e:
            # Check if the error is due to token expiration (e.g., 401 Unauthorized)
            if response.status_code == 401:
                print("Token expired, refreshing token...")
                self.auth.refresh_token()

                # Retry the request with the new token
                headers["Authorization"] = f"Bearer {self.auth.get_access_token()}"
                try:
                    response = requests.get(url, headers=headers)
                    response.raise_for_status()
                    config = response.json()
                    print(f"Trade configuration for account number {acc_num} after token refresh: {config}")
                    return config
                except requests.exceptions.RequestException as retry_error:
                    print(f"Failed to fetch configuration after token refresh: {retry_error}")
                    return None
            else:
                print(f"Failed to fetch configuration: {e}")
                return None
