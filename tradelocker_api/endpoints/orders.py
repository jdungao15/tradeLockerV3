import logging
from tradelocker_api.endpoints.auth import TradeLockerAuth
from tradelocker_api.api_client import ApiClient

logger = logging.getLogger(__name__)


class TradeLockerOrders(ApiClient):
    """
    Client for TradeLocker orders API with improved error handling and async support
    """

    def __init__(self, auth: TradeLockerAuth):
        super().__init__(auth)

    # Helper methods for order creation

    def _prepare_order_payload(self, instrument, quantity, side, order_type, price=None,
                               stop_price=None, take_profit=None, stop_loss=None):
        """
        Prepare order payload with validation
        """
        # Base payload
        payload = {
            "qty": quantity,
            "routeId": instrument['routes'][0]['id'],
            "side": side,  # 'buy' or 'sell'
            "tradableInstrumentId": instrument["tradableInstrumentId"],
            "type": order_type,  # 'market', 'limit', 'stop'
            "validity": "GTC" if order_type == "limit" else "IOC",  # GTC for limit, IOC for market
        }

        # Add conditional fields based on order type and parameters
        if order_type in ['limit', 'stop']:
            payload["price"] = price

        if order_type == "stop":
            payload["stopPrice"] = stop_price

        if stop_loss:
            payload["stopLoss"] = stop_loss
            payload["stopLossType"] = "absolute"

        if take_profit:
            payload["takeProfit"] = take_profit
            payload["takeProfitType"] = "absolute"

        # Remove keys that are None (optional fields not included)
        return {key: value for key, value in payload.items() if value is not None}

    # Synchronous methods (for backward compatibility)

    def create_order(self, account_id: int, acc_num: int, instrument: dict,
                     quantity: float, side: str, order_type: str, price: float = None,
                     stop_price: float = None, take_profit: float = None, stop_loss: float = None):
        """
        Place an order with the specified parameters.
        If the token is expired, it refreshes the token and retries the request.
        """
        try:
            # Prepare order payload
            payload = self._prepare_order_payload(
                instrument, quantity, side, order_type, price,
                stop_price, take_profit, stop_loss
            )

            # Prepare API request
            headers = {"accNum": str(acc_num)}
            endpoint = f"trade/accounts/{account_id}/orders"

            # Make the request with automatic retry
            response = self.request('POST', endpoint, headers=headers, json=payload)

            logger.info(f"Order placed successfully: {response}")
            return response

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None

    def get_orders(self, account_id: int, acc_num: int):
        """
        Get all orders for a specific account.
        """
        try:
            headers = {"accNum": str(acc_num)}
            endpoint = f"trade/accounts/{account_id}/orders"

            # Cache orders for a very short time (5 seconds)
            response = self.request('GET', endpoint, headers=headers, cache_ttl=5)

            return response
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            return None

    def cancel_order(self, account_id: int, acc_num: int, order_id: str):
        """
        Cancel an existing order.
        """
        try:
            headers = {"accNum": str(acc_num)}
            endpoint = f"trade/accounts/{account_id}/orders/{order_id}"

            response = self.request('DELETE', endpoint, headers=headers)

            logger.info(f"Order {order_id} cancelled successfully")
            return response
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return None

    # Asynchronous methods (for new code)

    async def create_order_async(self, account_id: int, acc_num: int, instrument: dict,
                                 quantity: float, side: str, order_type: str, price: float = None,
                                 stop_price: float = None, take_profit: float = None, stop_loss: float = None):
        """
        Place an order - async version.
        """
        try:
            # Prepare order payload
            payload = self._prepare_order_payload(
                instrument, quantity, side, order_type, price,
                stop_price, take_profit, stop_loss
            )

            # Prepare API request
            headers = {"accNum": str(acc_num)}
            endpoint = f"trade/accounts/{account_id}/orders"

            # Make the request with automatic retry
            response = await self.request_async('POST', endpoint, headers=headers, json=payload)

            logger.info(f"Order placed successfully: {response}")
            return response

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None

    async def get_orders_async(self, account_id: int, acc_num: int):
        """
        Get all orders for a specific account - async version.
        """
        try:
            headers = {"accNum": str(acc_num)}
            endpoint = f"trade/accounts/{account_id}/orders"

            # Cache orders for a very short time (5 seconds)
            response = await self.request_async('GET', endpoint, headers=headers, cache_ttl=5)

            return response
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            return None

    async def cancel_order_async(self, account_id, acc_num, order_id):
        """
        Cancel an existing order - async version.
        """
        try:
            headers = {"accNum": str(acc_num)}
            endpoint = f"trade/accounts/{account_id}/orders/{order_id}"

            response = await self.request_async('DELETE', endpoint, headers=headers)

            logger.info(f"Order {order_id} cancelled successfully")
            return response
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            # Rethrow so the caller can handle it
            raise

    async def place_orders_batch_async(self, account_id: int, acc_num: int, orders: list):
        """
        Place multiple orders in parallel - async version.

        Args:
            orders: List of order dictionaries, each containing all parameters for create_order_async
        """
        import asyncio

        try:
            tasks = []
            for order in orders:
                # Extract parameters from order dictionary
                instrument = order['instrument']
                quantity = order['quantity']
                side = order['side']
                order_type = order['order_type']
                price = order.get('price')
                stop_price = order.get('stop_price')
                take_profit = order.get('take_profit')
                stop_loss = order.get('stop_loss')

                # Create task
                task = self.create_order_async(
                    account_id, acc_num, instrument, quantity, side, order_type,
                    price, stop_price, take_profit, stop_loss
                )
                tasks.append(task)

            # Execute all order placements in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            successful_orders = []
            failed_orders = []

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error placing order: {result}")
                    failed_orders.append((orders[i], result))
                else:
                    successful_orders.append((orders[i], result))

            return {
                'successful': successful_orders,
                'failed': failed_orders
            }

        except Exception as e:
            logger.error(f"Error in batch order placement: {e}")
            return None