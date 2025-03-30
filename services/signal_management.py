import logging
import asyncio
import re
import aiohttp
import json
from datetime import datetime
from colorama import Fore, Style

from order_cache import OrderCache

logger = logging.getLogger(__name__)


class SignalManager:
    """
    Signal manager that handles trading commands through message replies.
    Uses order caching to track which orders correspond to which signals.
    """

    def __init__(self, accounts_client, orders_client, instruments_client, auth_client):
        self.accounts_client = accounts_client
        self.orders_client = orders_client
        self.instruments_client = instruments_client
        self.auth = auth_client
        self.order_cache = OrderCache()
        self.message_logs = []
        self.max_log_size = 200

        # Ensure initialization is complete
        self._init_complete = False
        self._initialize()

    def _initialize(self):
        """Initialize internal components"""
        # Ensure cache is loaded
        self.order_cache.load_cache()
        self._init_complete = True
        logger.info("Signal manager initialized")

    def log_message(self, message_data):
        """Log message data for debugging"""
        # Add timestamp
        message_data['timestamp'] = datetime.now().isoformat()

        # Add to logs
        self.message_logs.append(message_data)

        # Limit log size
        if len(self.message_logs) > self.max_log_size:
            self.message_logs = self.message_logs[-self.max_log_size:]

    def is_command_message(self, message):
        """
        Detect if a message contains a trading command using simple pattern matching
        without requiring AI processing.

        Args:
            message: Message text

        Returns:
            tuple: (command_type, tp_level) or (None, None) if not a command
        """
        if not message:
            return None, None

        message_lower = message.lower().strip()

        # Check for specific TP hit/close pattern with number (e.g., "TP1", "close TP2")
        tp_pattern = r"(?:close|hit|take|tp)\s*(?:tp|target|profit)?\s*(\d+)"
        tp_match = re.search(tp_pattern, message_lower)
        if tp_match:
            tp_level = int(tp_match.group(1))
            return 'tp', tp_level

        # Simple single-word commands
        if any(x in message_lower for x in ["breakeven", "be", "b/e", "b e"]):
            return 'breakeven', None

        if message_lower in ["close", "close all", "exit", "exit all"]:
            return 'close', None

        if message_lower in ["cancel", "cancel all"]:
            return 'cancel', None

        # Check for breakeven patterns
        breakeven_patterns = [
            r"move\s+(?:sl|stop(?:\s+loss)?)\s+to\s+(?:be|b/?e|breakeven|entry)",
            r"sl\s+(?:to\s+)?(?:be|b/?e|breakeven|entry)",
            r"(?:be|b/?e|breakeven)\s+(?:your\s+|the\s+)?(?:sl|stop(?:\s+loss)?)",
            r"lock\s+(?:in\s+)?profits",
            r"secure\s+(?:your\s+)?profits"
        ]

        for pattern in breakeven_patterns:
            if re.search(pattern, message_lower):
                return 'breakeven', None

        # Check for close patterns
        close_patterns = [
            r"close\s+(?:all|your|the)?\s+positions?",
            r"close\s+(?:all|your|the)?\s+trades?",
            r"exit\s+(?:all|your|the)?\s+positions?",
            r"exit\s+(?:all|your|the)?\s+trades?"
        ]

        for pattern in close_patterns:
            if re.search(pattern, message_lower):
                return 'close', None

        # Check for cancel patterns
        cancel_patterns = [
            r"cancel\s+(?:all|your|the)?\s+orders?",
            r"cancel\s+(?:all|your|the)?\s+trades?"
        ]

        for pattern in cancel_patterns:
            if re.search(pattern, message_lower):
                return 'cancel', None

        # Not a recognized command
        return None, None

    async def store_orders(self, message_id, order_ids, take_profits, instrument=None):
        """Store orders in the cache"""
        return self.order_cache.store_orders(
            message_id, order_ids, take_profits, instrument
        )

    async def cancel_order(self, account, order_id):
        """
        Cancel a pending order using direct API call
        Note: This method attempts to cancel without checking status first

        Args:
            account: Account information
            order_id: Order ID to cancel

        Returns:
            bool: Success status
        """
        try:
            url = f"{self.auth.base_url}/trade/orders/{order_id}"
            headers = {
                "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                "accNum": str(account['accNum'])
            }

            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    success = response.status == 200
                    if success:
                        logger.info(f"Successfully cancelled order {order_id}")
                    else:
                        # Don't treat as error if 404 - just means it was already executed or cancelled
                        if response.status == 404:
                            logger.info(f"Order {order_id} not found - may have been executed or already cancelled")
                        else:
                            error_text = await response.text()
                            logger.warning(f"Failed to cancel order {order_id}: {response.status} - {error_text}")
                    return success
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def close_position(self, account, position_id):
        """
        Close a position using direct API call
        Note: This method attempts to close without checking status first

        Args:
            account: Account information
            position_id: Position ID to close

        Returns:
            bool: Success status
        """
        try:
            url = f"{self.auth.base_url}/trade/positions/{position_id}"
            headers = {
                "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                "accNum": str(account['accNum']),
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers) as response:
                    success = response.status == 200
                    if success:
                        logger.info(f"Successfully closed position {position_id}")
                    else:
                        # Don't treat as error if 404 - just means it was already closed
                        if response.status == 404:
                            logger.info(f"Position {position_id} not found - may have been already closed")
                        else:
                            error_text = await response.text()
                            logger.warning(f"Failed to close position {position_id}: {response.status} - {error_text}")
                    return success
        except Exception as e:
            logger.error(f"Error closing position {position_id}: {e}")
            return False


    async def set_breakeven(self, account, position_id, entry_price=None):
        """
        Set stop loss to breakeven for a position - simplified implementation

        Args:
            account: Account information
            position_id: Position ID
            entry_price: Optional entry price from cache

        Returns:
            bool: Success status
        """
        try:
            # Create API request for setting stop loss to entry price
            url = f"{self.auth.base_url}/trade/positions/{position_id}"
            headers = {
                "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                "accNum": str(account['accNum']),
                "Content-Type": "application/json"
            }

            # Use provided entry price or default to 0 (which will fail)
            stop_loss = entry_price
            if not stop_loss:
                logger.error(f"No entry price available for position {position_id}")
                return False

            # Send only the stopLoss in the body as per API requirements
            body = {"stopLoss": stop_loss}

            # Execute the PATCH request
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=body) as response:
                    success = response.status == 200
                    if success:
                        logger.info(f"Successfully moved SL to breakeven for position {position_id}: {stop_loss}")
                    else:
                        error_text = await response.text()
                        logger.warning(
                            f"Failed to update SL for position {position_id}: {response.status} - {error_text}")
                    return success

        except Exception as e:
            logger.error(f"Error moving SL to breakeven: {e}")
            return False

    def _get_pip_size(self, instrument_name):
        """
        Get pip size for the instrument

        Args:
            instrument_name: Name of the instrument

        Returns:
            float: Pip size
        """
        instrument_upper = instrument_name.upper() if instrument_name else ""

        if instrument_upper.endswith("JPY"):
            return 0.01
        elif "XAU" in instrument_upper or "GOLD" in instrument_upper:
            return 0.1
        elif any(name in instrument_upper for name in ["DJI30", "DOW", "US30"]):
            return 1.0
        else:
            return 0.0001  # Default for most forex pairs

    async def handle_message(self, message, account, colored_time, reply_to_msg_id=None, message_id=None):
        """
        Process an incoming message to check for trading commands
        When a TP command is received, cancel ALL pending orders for the message
        """
        # Log the message for debugging
        message_log = {
            'message': message,
            'reply_to_msg_id': reply_to_msg_id,
            'message_id': message_id,
            'is_command': False
        }

        # Check if this is a command message
        command_type, tp_level = self.is_command_message(message)

        if not command_type:
            self.log_message(message_log)
            return False, None

        # Update log with command details
        message_log['is_command'] = True
        message_log['command_type'] = command_type
        message_log['tp_level'] = tp_level

        # Check if we have a reply_to_msg_id to associate with orders
        if not reply_to_msg_id:
            logger.info(f"{colored_time}: Command detected but no reply-to message ID")
            message_log['match_method'] = 'none_no_reply_id'
            self.log_message(message_log)
            return False, None

        # Log detailed information about the IDs we're working with
        logger.info(
            f"{colored_time}: Looking for cached orders with reply_to_msg_id: {reply_to_msg_id} (type: {type(reply_to_msg_id).__name__})")

        # Try to get orders associated with the original message
        cached_orders = self.order_cache.get_orders(reply_to_msg_id)

        if not cached_orders:
            logger.info(f"{colored_time}: No cached orders found for message ID {reply_to_msg_id}")
            message_log['match_method'] = 'none_no_cached_orders'
            self.log_message(message_log)
            return False, None

        # We found cached orders, so we can process the command
        order_ids = cached_orders.get('orders', [])
        take_profits = cached_orders.get('take_profits', [])
        instrument = cached_orders.get('instrument')

        logger.info(
            f"{colored_time}: {Fore.CYAN}Found {len(order_ids)} cached orders for message {reply_to_msg_id}. "
            f"Command: {command_type}{' TP' + str(tp_level) if tp_level else ''}{Style.RESET_ALL}"
        )

        # Initialize counters
        success_count = 0
        total_count = len(order_ids)
        message_log['match_method'] = 'cached_orders'

        # HANDLE COMMANDS DIFFERENTLY

        if command_type == 'tp':
            # For TP commands (with or without level), cancel ALL pending orders
            # Don't close active positions

            logger.info(
                f"{colored_time}: TP command received - attempting to cancel ALL {len(order_ids)} pending orders")

            # Process all orders in parallel for speed
            cancel_tasks = []
            for order_id in order_ids:
                task = asyncio.create_task(self.cancel_order(account, order_id))
                cancel_tasks.append((order_id, task))

            # Wait for all cancel operations to complete
            for order_id, task in cancel_tasks:
                try:
                    success = await task
                    if success:
                        # Remove the order from cache after successful cancellation
                        self.order_cache.remove_order(reply_to_msg_id, order_id)
                        logger.info(f"{colored_time}: {Fore.YELLOW}Cancelled pending order {order_id}{Style.RESET_ALL}")
                        success_count += 1
                    else:
                        logger.info(f"{colored_time}: Order {order_id} is not a pending order or already executed")
                except Exception as e:
                    logger.error(f"{colored_time}: Error cancelling order {order_id}: {e}")

            # If all orders were successfully cancelled, remove the message
            if success_count > 0:
                remaining_orders = await self.get_remaining_orders_count(reply_to_msg_id)
                if remaining_orders == 0:
                    self.order_cache.remove_message(reply_to_msg_id)
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}All orders cancelled, removed message {reply_to_msg_id} from cache{Style.RESET_ALL}")


        elif command_type == 'close':
            # Use the same parallel processing logic that works for TP and cancel

            logger.info(
                f"{colored_time}: Close command received - attempting to close ALL {len(order_ids)} orders/positions")

            # Process all orders in parallel for speed
            close_tasks = []

            for order_id in order_ids:
                # For close command, we first try cancel_order to handle pending orders

                task = asyncio.create_task(self.cancel_order(account, order_id))
                close_tasks.append(('cancel', order_id, task))

            # Wait for all cancel operations to complete
            for op_type, order_id, task in close_tasks:

                try:
                    success = await task
                    if success:
                        # Successfully cancelled as pending order

                        self.order_cache.remove_order(reply_to_msg_id, order_id)
                        logger.info(f"{colored_time}: {Fore.YELLOW}Cancelled pending order {order_id}{Style.RESET_ALL}")
                        success_count += 1

                    else:
                        # If not a pending order, try to close as position
                        close_success = await self.close_position(account, order_id)

                        if close_success:
                            self.order_cache.remove_order(reply_to_msg_id, order_id)
                            logger.info(
                                f"{colored_time}: {Fore.GREEN}Closed active position {order_id}{Style.RESET_ALL}")
                            success_count += 1
                        else:
                            logger.info(f"{colored_time}: Failed to close/cancel order/position {order_id}")

                except Exception as e:
                    logger.error(f"{colored_time}: Error processing order {order_id}: {e}")

            # If we successfully processed any orders, check if we should remove the message
            if success_count > 0:
                remaining_orders = await self.get_remaining_orders_count(reply_to_msg_id)
                if remaining_orders == 0:
                    self.order_cache.remove_message(reply_to_msg_id)
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}All orders processed, removed message {reply_to_msg_id} from cache{Style.RESET_ALL}")



        elif command_type == 'cancel':
            # Use the same logic that works for TP command
            # Process all orders in parallel for efficiency

            logger.info(f"{colored_time}: Cancel command received - attempting to cancel ALL {len(order_ids)} orders")

            # Process all orders in parallel for speed

            cancel_tasks = []
            for order_id in order_ids:
                task = asyncio.create_task(self.cancel_order(account, order_id))

                cancel_tasks.append((order_id, task))

            # Wait for all cancel operations to complete
            for order_id, task in cancel_tasks:
                try:
                    success = await task
                    if success:
                        # Remove the order from cache after successful cancellation
                        self.order_cache.remove_order(reply_to_msg_id, order_id)
                        logger.info(f"{colored_time}: {Fore.YELLOW}Cancelled order {order_id}{Style.RESET_ALL}")
                        success_count += 1

                    else:
                        # If cancellation didn't work, try to close as position
                        close_success = await self.close_position(account, order_id)
                        if close_success:
                            self.order_cache.remove_order(reply_to_msg_id, order_id)
                            logger.info(f"{colored_time}: {Fore.GREEN}Closed position {order_id}{Style.RESET_ALL}")
                            success_count += 1
                        else:
                            logger.info(f"{colored_time}: Failed to cancel order or close position {order_id}")
                except Exception as e:
                    logger.error(f"{colored_time}: Error processing order {order_id}: {e}")

            # If we successfully processed any orders, check if we should remove the message
            if success_count > 0:
                remaining_orders = await self.get_remaining_orders_count(reply_to_msg_id)
                if remaining_orders == 0:
                    self.order_cache.remove_message(reply_to_msg_id)
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}All orders processed, removed message {reply_to_msg_id} from cache{Style.RESET_ALL}")


        elif command_type == 'breakeven':
            # For breakeven command, use entry price from cache
            # Get the entry price from the cached data
            entry_price = cached_orders.get('entry_price')

            if not entry_price:
                logger.warning(f"{colored_time}: No entry price found in cache for message {reply_to_msg_id}")
            # Process each order
            for order_id in order_ids:
                be_success = await self.set_breakeven(account, order_id, entry_price)
                if be_success:
                    logger.info(f"{colored_time}: {Fore.CYAN}Set breakeven for position {order_id}{Style.RESET_ALL}")
                    success_count += 1
                    continue
                logger.warning(f"{colored_time}: Failed to set breakeven for position {order_id}")
        # Return the result
        result = {
            "command_type": command_type,
            "tp_level": tp_level,
            "success_count": success_count,
            "total_count": total_count,
            "message_id": reply_to_msg_id,
            "instrument": instrument
        }

        message_log['success'] = success_count > 0
        message_log['success_count'] = success_count
        message_log['total_count'] = total_count
        self.log_message(message_log)

        return True, result

    async def get_remaining_orders_count(self, message_id):
        """Helper to check how many orders remain for a message"""
        orders_data = self.order_cache.get_orders(message_id)
        if not orders_data:
            return 0
        return len(orders_data.get('orders', []))

    def export_message_logs(self, limit=None):
        """Export message logs for debugging/analysis"""
        logs_to_export = self.message_logs
        if limit:
            logs_to_export = logs_to_export[-limit:]
        return json.dumps(logs_to_export, indent=2)