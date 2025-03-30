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
        Detect if a message contains a trading command

        Args:
            message: Message text

        Returns:
            tuple: (command_type, tp_level) or (None, None) if not a command
        """
        if not message:
            return None, None

        message_lower = message.lower().strip()

        # Simple single-word commands
        if message_lower in ["breakeven", "be"]:
            return 'breakeven', None

        if message_lower in ["close", "cancel", "exit"]:
            return 'close', None

        # Check for TP hit/close pattern
        tp_pattern = r"(?:close|hit|take|tp)\s*(?:tp|target|profit)?\s*(\d+)"
        tp_match = re.search(tp_pattern, message_lower)
        if tp_match:
            tp_level = int(tp_match.group(1))
            return 'tp', tp_level

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

        # Not a recognized command
        return None, None

    async def store_orders(self, message_id, order_ids, take_profits, instrument=None):
        """Store orders in the cache"""
        return self.order_cache.store_orders(
            message_id, order_ids, take_profits, instrument
        )

    async def check_order_status(self, account, order_id):
        """
        Check if an order is still pending or has become an active position

        Args:
            account: Account information
            order_id: Order ID to check

        Returns:
            tuple: (status, order_type) - status: 'pending'|'active'|'unknown', order_type: 'order'|'position'|None
        """
        try:
            # First try to get it as a pending order
            url = f"{self.auth.base_url}/trade/orders/{order_id}"
            headers = {
                "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                "accNum": str(account['accNum'])
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        # Order exists
                        return 'pending', 'order'

            # If not found as pending order, try as active position
            url = f"{self.auth.base_url}/trade/positions/{order_id}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        # Position exists
                        return 'active', 'position'

            # Not found as either order or position
            return 'unknown', None

        except Exception as e:
            logger.error(f"Error checking order status: {e}")
            return 'unknown', None

    async def cancel_order(self, account, order_id):
        """
        Cancel a pending order using direct API call

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
                        error_text = await response.text()
                        logger.error(f"Failed to cancel order {order_id}: {response.status} - {error_text}")
                    return success
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def close_position(self, account, position_id):
        """
        Close a position using direct API call

        Args:
            account: Account information
            position_id: Position ID to close

        Returns:
            bool: Success status
        """
        try:
            url = f"{self.auth.base_url}/trade/positions/{position_id}/close"
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
                        error_text = await response.text()
                        logger.error(f"Failed to close position {position_id}: {response.status} - {error_text}")
                    return success
        except Exception as e:
            logger.error(f"Error closing position {position_id}: {e}")
            return False

    async def get_position_details(self, account, position_id):
        """
        Get position details for a specific position ID

        Args:
            account: Account information
            position_id: Position ID

        Returns:
            dict: Position details or None if not found
        """
        try:
            url = f"{self.auth.base_url}/trade/positions/{position_id}"
            headers = {
                "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                "accNum": str(account['accNum'])
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('d', {})
                    else:
                        logger.error(f"Failed to get position details for {position_id}: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting position details: {e}")
            return None

    async def set_breakeven(self, account, position_id):
        """
        Set stop loss to breakeven for a position

        Args:
            account: Account information
            position_id: Position ID

        Returns:
            bool: Success status
        """
        try:
            # First get position details to find the entry price
            position_details = await self.get_position_details(account, position_id)

            if not position_details:
                logger.error(f"Could not get position details for {position_id}")
                return False

            # Extract necessary data
            if 'position' not in position_details:
                logger.error(f"No position data found for {position_id}")
                return False

            position_data = position_details['position']

            # Get entry price and side
            entry_price = float(position_data.get('entryPrice', 0))
            if entry_price == 0:
                logger.error(f"Invalid entry price 0 for position {position_id}")
                return False

            side = position_data.get('side', '').lower()
            instrument_data = position_data.get('tradableInstrument', {})
            instrument_name = instrument_data.get('name', '')

            # Determine pip size based on instrument
            pip_size = self._get_pip_size(instrument_name)

            # Calculate buffer (default 2 pips)
            buffer_pips = 2
            buffer_amount = buffer_pips * pip_size

            # Calculate new SL with buffer
            if side == 'buy':
                new_sl = entry_price - buffer_amount
            else:
                new_sl = entry_price + buffer_amount

            # Format the new SL to match instrument precision
            new_sl = round(new_sl, 5)

            # Update the stop loss via API
            url = f"{self.auth.base_url}/trade/positions/{position_id}"
            headers = {
                "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                "accNum": str(account['accNum']),
                "Content-Type": "application/json"
            }
            body = {"stopLoss": new_sl}

            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=body) as response:
                    success = response.status == 200
                    if success:
                        logger.info(f"Successfully moved SL to breakeven for position {position_id}: {new_sl}")
                    else:
                        error_text = await response.text()
                        logger.error(
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

        Args:
            message: Message text
            account: Account information
            colored_time: Formatted time for logging
            reply_to_msg_id: ID of the message this is replying to
            message_id: ID of this message

        Returns:
            tuple: (is_handled, result_info)
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
            self.log_message(message_log)
            return False, None

        # Try to get orders associated with the original message
        cached_orders = self.order_cache.get_orders(reply_to_msg_id)

        if not cached_orders:
            logger.info(f"{colored_time}: No cached orders found for message ID {reply_to_msg_id}")
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

        # Execute the appropriate command for each order
        success_count = 0
        total_count = len(order_ids)

        for order_index, order_id in enumerate(order_ids):
            # If command is to close a specific TP level, check if this order corresponds to that TP
            if command_type == 'tp' and tp_level and take_profits:
                # Check if the number of orders matches number of TPs
                if len(order_ids) == len(take_profits):
                    # If order index doesn't match TP level-1, skip it
                    if order_index != (tp_level - 1):
                        logger.info(f"Skipping order {order_id} as it doesn't match TP{tp_level}")
                        continue

            # Check if order is pending or active
            status, order_type = await self.check_order_status(account, order_id)

            if status == 'unknown':
                logger.warning(f"Order/position {order_id} not found - may have been already closed")
                continue

            # Handle based on command type and order status
            if command_type in ['close', 'tp']:
                if status == 'pending':
                    # Cancel pending order
                    cancel_success = await self.cancel_order(account, order_id)
                    if cancel_success:
                        success_count += 1
                        self.order_cache.update_order_status(reply_to_msg_id, order_id, 'cancelled')
                        logger.info(f"{colored_time}: {Fore.YELLOW}Cancelled order {order_id}{Style.RESET_ALL}")

                elif status == 'active':
                    # Close active position
                    close_success = await self.close_position(account, order_id)
                    if close_success:
                        success_count += 1
                        self.order_cache.update_order_status(reply_to_msg_id, order_id, 'closed')
                        logger.info(f"{colored_time}: {Fore.GREEN}Closed position {order_id}{Style.RESET_ALL}")

            elif command_type == 'breakeven' and status == 'active':
                # Set breakeven only for active positions
                be_success = await self.set_breakeven(account, order_id)
                if be_success:
                    success_count += 1
                    self.order_cache.update_order_status(reply_to_msg_id, order_id, 'breakeven')
                    logger.info(f"{colored_time}: {Fore.CYAN}Set breakeven for position {order_id}{Style.RESET_ALL}")

        # Return the result
        result = {
            "command_type": command_type,
            "tp_level": tp_level,
            "success_count": success_count,
            "total_count": total_count,
            "message_id": reply_to_msg_id,
            "instrument": instrument
        }

        self.log_message(message_log)
        return True, result

    def export_message_logs(self, limit=None):
        """Export message logs for debugging/analysis"""
        logs_to_export = self.message_logs
        if limit:
            logs_to_export = logs_to_export[-limit:]
        return json.dumps(logs_to_export, indent=2)