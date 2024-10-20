import requests
from tradelocker_api.auth import TradeLockerAuth


class TradeLockerOrders:
    def __init__(self, auth: TradeLockerAuth):
        self.auth = auth
        self.base_url = auth.base_url

    def create_order(self, account_id: int, acc_num: int, instrument: dict,
                     quantity: float, side: str, order_type: str, price: float = None,
                     stop_price: float = None, take_profit: float = None, stop_loss: float = None):
        """
        Place an order with the specified parameters.
        If the token is expired, it refreshes the token and retries the request.
        """
        def place_order_request(headers, payload):
            url = f"{self.base_url}/trade/accounts/{account_id}/orders"
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response

        access_token = self.auth.get_access_token()
        url = f"{self.base_url}/trade/accounts/{account_id}/orders"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "accNum": str(acc_num),  # Required by the API as shown in the image
            "Content-Type": "application/json"
        }
        payload = {
            "price": price if order_type in ['limit', 'stop'] else 0,  # Price for limit/stop orders
            "qty": quantity,
            "routeId": instrument['routes'][0]['id'],
            "side": side,  # 'buy' or 'sell'
            "stopLoss": stop_loss,  # Optional stop-loss
            "stopLossType": "absolute" if stop_loss else None,  # Stop-loss type
            "stopPrice": stop_price if order_type == "stop" else None,  # Required for stop orders
            "takeProfit": take_profit,  # Optional take-profit
            "takeProfitType": "absolute" if take_profit else None,  # Take-profit type
            "trStopOffset": 0,
            "tradableInstrumentId": instrument["tradableInstrumentId"],
            "type": order_type,  # 'market', 'limit', 'stop'
            "validity": "GTC" if order_type == "limit" else "IOC",  # GTC for limit, IOC for market
        }

        # Remove keys that are None (optional fields not included)
        payload = {key: value for key, value in payload.items() if value is not None}

        try:
            # Try placing the order and handle token expiration
            response = place_order_request(headers, payload)
            print(f"Order placed successfully: {response.json()}")
            return response.json()

        except requests.exceptions.HTTPError as e:
            # Check if the error is due to token expiration (e.g., 401 Unauthorized)
            if response.status_code == 401:
                print("Token expired, refreshing token...")
                refresh_token = self.auth.refresh_token()
                print(f"Refreshed Token orders.py {refresh_token}")

                # Retry the request with the new token
                headers["Authorization"] = f"Bearer {self.auth.get_access_token()}"
                try:
                    response = place_order_request(headers, payload)
                    print(f"Order placed successfully after token refresh: {response.json()}")
                    return response.json()
                except requests.exceptions.RequestException as retry_error:
                    print(f"Failed to place order after retry: {retry_error}")
                    return None
            else:
                print(f"Failed to place order: {e}")
                return None

    def get_orders(self, account_id: int, acc_num: int):
        """
        Get all orders for a specific account.
        """
        url = f"{self.base_url}/trade/accounts/{account_id}/orders"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num),  # Required header
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch orders: {e}")
            return None
