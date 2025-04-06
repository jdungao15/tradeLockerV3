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
    Enhanced Signal manager that handles trading commands through message replies.
    Now includes content-based fallback matching for forwarded signals.
    """

    def __init__(self, accounts_client, orders_client, instruments_client, auth_client):
        self.accounts_client = accounts_client
        self.orders_client = orders_client
        self.instruments_client = instruments_client
        self.auth = auth_client
        self.order_cache = OrderCache()
        self.message_logs = []
        self.max_log_size = 200
        self.content_matching_enabled = True  # Flag to enable/disable content matching
        self.max_content_match_age = 24  # Hours to search back for content matches
        self.debug_mode = False  # Enable for verbose debug logging

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
        Detect if a message contains a trading command using robust pattern matching
        that can handle natural language variations used by signal providers.

        Args:
            message: Message text

        Returns:
            tuple: (command_type, tp_level) or (None, None) if not a command
        """
        if not message:
            return None, None

        message_lower = message.lower().strip()

        # Log the message we're trying to detect
        logger.info(f"Checking if message is a command: '{message_lower}'")

        # 1. SIMPLE KEYWORD DETECTION (Most reliable)
        # Check for the presence of simple command keywords at the beginning of the message

        # Close detection - look for "close" at the beginning
        if message_lower.startswith("close"):
            logger.info(f"Detected CLOSE command: '{message_lower}'")
            return 'close', None

        # Cancel detection - look for "cancel" at the beginning
        if message_lower.startswith("cancel"):
            logger.info(f"Detected CANCEL command: '{message_lower}'")
            return 'cancel', None

        # Breakeven detection - look for "be" or "breakeven" at the beginning
        if message_lower.startswith(("be ", "breakeven")):
            logger.info(f"Detected BREAKEVEN command: '{message_lower}'")
            return 'breakeven', None

        # 2. CHECK FOR TP COMMANDS (HIGHEST PRIORITY)

        # Check for specific TP hit/close pattern with number (e.g., "TP1", "close TP2", "Take Profit 3 hit")
        tp_pattern = r"(?:close|hit|take|tp|target|profit)[\s\-_.]*(?:tp|target|profit)?[\s\-_.]*(\d+)"
        tp_match = re.search(tp_pattern, message_lower)
        if tp_match:
            tp_level = int(tp_match.group(1))
            logger.info(f"Detected TP command with level {tp_level}: '{message_lower}'")
            return 'tp', tp_level

        # 3. CHECK FOR DETAILED COMMAND PATTERNS

        # More comprehensive patterns for breakeven
        be_keywords = [
            r"break[\s\-_.]*even",
            r"\bbe\b",
            r"b[/\s\-_.]*e",
            r"move[\s\-_.]*(?:sl|stop|loss)[\s\-_.]*to[\s\-_.]*(?:entry|be|breakeven)",
            r"(?:sl|stop|loss)[\s\-_.]*(?:at|to)[\s\-_.]*(?:entry|be|breakeven)",
            r"lock[\s\-_.]*(?:in)?[\s\-_.]*profits?",
            r"secure[\s\-_.]*(?:your|the)?[\s\-_.]*profits?"
        ]

        for pattern in be_keywords:
            if re.search(pattern, message_lower):
                logger.info(f"Detected BREAKEVEN command (detailed pattern): '{message_lower}'")
                return 'breakeven', None

        # More comprehensive patterns for closing
        close_keywords = [
            r"close[\s\-_.]*(?:all|your|the|this|early|now)?[\s\-_.]*(?:positions?|trades?|orders?)",
            r"exit[\s\-_.]*(?:all|your|the|this|early|now)?[\s\-_.]*(?:positions?|trades?|orders?)",
            r"get[\s\-_.]*out",
            r"take[\s\-_.]*profit[\s\-_.]*now",
            r"exit[\s\-_.]*(?:all|now|market|immediately)",
            r"close[\s\-_.]*(?:all|now|market|immediately|early)",  # Added explicit "close early" pattern
            r"market[\s\-_.]*(?:doesn't|not|isn't)[\s\-_.]*(?:look|seem)[\s\-_.]*good"
        ]

        for pattern in close_keywords:
            if re.search(pattern, message_lower):
                logger.info(f"Detected CLOSE command (detailed pattern): '{message_lower}'")
                return 'close', None

        # More comprehensive patterns for cancelling
        cancel_keywords = [
            r"cancel[\s\-_.]*(?:all|your|the|this|now)?[\s\-_.]*(?:positions?|trades?|orders?)?",
            r"abort[\s\-_.]*(?:all|your|the|this|now)?[\s\-_.]*(?:positions?|trades?|orders?)?",
            r"remove[\s\-_.]*(?:all|your|the|this|now)?[\s\-_.]*(?:positions?|trades?|orders?)?",
            r"delete[\s\-_.]*(?:all|your|the|this|now)?[\s\-_.]*(?:positions?|trades?|orders?)?",
            r"stop[\s\-_.]*(?:all|your|the|this|now)?[\s\-_.]*(?:positions?|trades?|orders?)?",
            r"missed[\s\-_.]*(?:the|this)?[\s\-_.]*(?:entry|signal|opportunity)"
        ]

        for pattern in cancel_keywords:
            if re.search(pattern, message_lower):
                logger.info(f"Detected CANCEL command (detailed pattern): '{message_lower}'")
                return 'cancel', None

        # 4. CHECK FOR GENERIC TP COMMAND WITHOUT NUMBER

        # Generic TP patterns without specific number
        generic_tp_patterns = [
            r"\btp\b",
            r"take[\s\-_.]*profit",
            r"target[\s\-_.]*hit",
            r"target[\s\-_.]*reached"
        ]

        for pattern in generic_tp_patterns:
            if re.search(pattern, message_lower):
                # If we find a generic TP pattern without a number
                logger.info(f"Detected generic TP command: '{message_lower}'")
                return 'tp', None

        # 5. SUPER SIMPLE WORD MATCHING (FALLBACK)

        # Last resort - check if the key command words appear anywhere in the message
        if "close" in message_lower:
            logger.info(f"Detected CLOSE command (simple word match): '{message_lower}'")
            return 'close', None

        if "cancel" in message_lower:
            logger.info(f"Detected CANCEL command (simple word match): '{message_lower}'")
            return 'cancel', None

        if "breakeven" in message_lower or " be " in message_lower:
            logger.info(f"Detected BREAKEVEN command (simple word match): '{message_lower}'")
            return 'breakeven', None

        # Not a recognized command
        logger.info(f"No command detected in message: '{message_lower}'")
        return None, None

    def extract_trading_parameters(self, message):
        """
        Extract parameters from a message for content-based matching.
        Extracts instrument, entry points, stop loss, take profits.

        Args:
            message: Command message text

        Returns:
            dict: Dictionary with extracted parameters
        """
        if not message:
            return {}

        message = message.lower()
        result = {
            'instrument': None,
            'entry_price': None,
            'stop_loss': None,
            'take_profits': []
        }

        # Extract instrument
        # Common instruments
        common_instruments = [
            "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd",
            "gold", "xauusd", "silver", "xagusd",
            "us30", "dji30", "dow", "nasdaq", "nas100", "ndx100", "spx", "sp500"
        ]

        # Find any instrument mentions
        for instrument in common_instruments:
            if instrument in message:
                result['instrument'] = instrument.upper()
                break

        # Try to extract forex pairs (six alpha characters)
        if not result['instrument']:
            forex_pattern = r'\b([a-z]{3}[a-z]{3})\b'
            match = re.search(forex_pattern, message)
            if match:
                result['instrument'] = match.group(1).upper()

        # Extract prices - find all numbers in the message
        price_pattern = r'\b(\d+\.?\d*)\b'
        prices = re.findall(price_pattern, message)
        prices = [float(p) for p in prices]

        # If fewer than 2 prices found, return what we have
        if len(prices) < 2:
            return result

        # Try to associate prices with entry, SL, TP
        # Look for labeled prices
        entry_pattern = r'entry[\s\-_.]*(?:price|point|level)?[\s\-_.]*(?:at|:)?[\s\-_.]*(\d+\.?\d*)'
        sl_pattern = r'(?:sl|stop[\s\-_.]*loss)[\s\-_.]*(?:at|:)?[\s\-_.]*(\d+\.?\d*)'
        tp_pattern = r'(?:tp|target|take[\s\-_.]*profit)[\s\-_.]*(?:at|:)?[\s\-_.]*(\d+\.?\d*)'

        # Try to find labeled prices
        entry_match = re.search(entry_pattern, message)
        if entry_match:
            result['entry_price'] = float(entry_match.group(1))

        sl_match = re.search(sl_pattern, message)
        if sl_match:
            result['stop_loss'] = float(sl_match.group(1))

        # Extract all take profits
        tp_matches = re.findall(tp_pattern, message)
        if tp_matches:
            result['take_profits'] = [float(tp) for tp in tp_matches]

        # If we didn't find labeled prices, make educated guesses
        if not result['entry_price'] and len(prices) >= 2:
            # In commands, entry price is often mentioned first
            result['entry_price'] = prices[0]

        if not result['stop_loss'] and len(prices) >= 2:
            # Stop loss is often the lowest/highest price depending on the trade direction
            # But without knowing the direction, we'll just use the second mentioned price
            result['stop_loss'] = prices[1]

        return result

    async def store_orders(self, message_id, order_ids, take_profits, instrument=None, entry_price=None,
                           stop_loss=None):
        """Store orders in the cache"""
        return self.order_cache.store_orders(
            message_id, order_ids, take_profits, instrument, entry_price, stop_loss
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

    async def find_matching_orders(self, command_message, account, reply_to_msg_id, colored_time):
        """
        Find orders that match the command message content
        when direct message ID matching fails.

        Args:
            command_message: Command message content
            account: Account information
            reply_to_msg_id: Original message ID that was replied to
            colored_time: Formatted time for logging

        Returns:
            tuple: (match_found, msg_id, cached_orders) or (False, None, None) if no match
        """
        # First try exact message ID match
        cached_orders = self.order_cache.get_orders(reply_to_msg_id)
        if cached_orders:
            logger.info(f"{colored_time}: Found exact message ID match for {reply_to_msg_id}")
            return True, reply_to_msg_id, cached_orders

        # If no direct match and content matching is disabled, return early
        if not self.content_matching_enabled:
            logger.info(f"{colored_time}: No exact match and content matching is disabled")
            return False, None, None

        logger.info(f"{colored_time}: No exact message ID match. Attempting content-based matching...")

        # Extract trading parameters from command message
        params = self.extract_trading_parameters(command_message)

        # Debug log extracted parameters
        if self.debug_mode:
            logger.debug(f"Extracted parameters: {json.dumps(params)}")

        # Need at least an instrument to attempt matching
        if not params.get('instrument'):
            logger.info(f"{colored_time}: No instrument found in command. Content matching aborted.")
            return False, None, None

        # Use the OrderCache's find_orders_by_content method
        message_id, cached_data = self.order_cache.find_orders_by_content(
            instrument=params.get('instrument'),
            entry_price=params.get('entry_price'),
            stop_loss=params.get('stop_loss'),
            take_profits=params.get('take_profits'),
            max_age_hours=self.max_content_match_age
        )

        if message_id and cached_data:
            logger.info(
                f"{colored_time}: {Fore.GREEN}Found content match with message ID {message_id}{Style.RESET_ALL}")
            return True, message_id, cached_data

        logger.info(f"{colored_time}: {Fore.YELLOW}No content match found.{Style.RESET_ALL}")
        return False, None, None

    async def handle_message(self, message, account, colored_time, reply_to_msg_id=None, message_id=None):
        """
        Process an incoming message to check for trading commands
        Enhanced with content-based fallback matching for forwarded signals
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

        # Try to match orders - either by exact message ID or content
        match_found, matched_msg_id, cached_orders = await self.find_matching_orders(
            message, account, reply_to_msg_id, colored_time
        )

        if not match_found:
            logger.info(f"{colored_time}: No matching orders found for this command")
            message_log['match_method'] = 'none_no_matches'
            self.log_message(message_log)
            return False, None

        # Get the matched data
        order_ids = cached_orders.get('orders', [])
        take_profits = cached_orders.get('take_profits', [])
        instrument = cached_orders.get('instrument')
        entry_price = cached_orders.get('entry_price')
        stop_loss = cached_orders.get('stop_loss')

        logger.info(
            f"{colored_time}: {Fore.CYAN}Found {len(order_ids)} cached orders for message {matched_msg_id}. "
            f"Command: {command_type}{' TP' + str(tp_level) if tp_level else ''}{Style.RESET_ALL}"
        )

        # Initialize counters
        success_count = 0
        total_count = len(order_ids)

        # Set match method based on whether we matched directly or by content
        if str(matched_msg_id) == str(reply_to_msg_id):
            message_log['match_method'] = 'exact_message_id'
        else:
            message_log['match_method'] = 'content_match'
            logger.info(
                f"{colored_time}: {Fore.YELLOW}Using content-based match. Original message ID: {reply_to_msg_id}, Matched message ID: {matched_msg_id}{Style.RESET_ALL}")

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
                        self.order_cache.remove_order(matched_msg_id, order_id)
                        logger.info(f"{colored_time}: {Fore.YELLOW}Cancelled pending order {order_id}{Style.RESET_ALL}")
                        success_count += 1
                    else:
                        logger.info(f"{colored_time}: Order {order_id} is not a pending order or already executed")
                except Exception as e:
                    logger.error(f"{colored_time}: Error cancelling order {order_id}: {e}")

            # If all orders were successfully cancelled, remove the message
            if success_count > 0:
                remaining_orders = await self.get_remaining_orders_count(matched_msg_id)
                if remaining_orders == 0:
                    self.order_cache.remove_message(matched_msg_id)
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}All orders cancelled, removed message {matched_msg_id} from cache{Style.RESET_ALL}")


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

                        self.order_cache.remove_order(matched_msg_id, order_id)
                        logger.info(f"{colored_time}: {Fore.YELLOW}Cancelled pending order {order_id}{Style.RESET_ALL}")
                        success_count += 1

                    else:
                        # If not a pending order, try to close as position
                        close_success = await self.close_position(account, order_id)

                        if close_success:
                            self.order_cache.remove_order(matched_msg_id, order_id)
                            logger.info(
                                f"{colored_time}: {Fore.GREEN}Closed active position {order_id}{Style.RESET_ALL}")
                            success_count += 1
                        else:
                            logger.info(f"{colored_time}: Failed to close/cancel order/position {order_id}")

                except Exception as e:
                    logger.error(f"{colored_time}: Error processing order {order_id}: {e}")

            # If we successfully processed any orders, check if we should remove the message
            if success_count > 0:
                remaining_orders = await self.get_remaining_orders_count(matched_msg_id)
                if remaining_orders == 0:
                    self.order_cache.remove_message(matched_msg_id)
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}All orders processed, removed message {matched_msg_id} from cache{Style.RESET_ALL}")



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
                        self.order_cache.remove_order(matched_msg_id, order_id)
                        logger.info(f"{colored_time}: {Fore.YELLOW}Cancelled order {order_id}{Style.RESET_ALL}")
                        success_count += 1

                    else:
                        # If cancellation didn't work, try to close as position
                        close_success = await self.close_position(account, order_id)
                        if close_success:
                            self.order_cache.remove_order(matched_msg_id, order_id)
                            logger.info(f"{colored_time}: {Fore.GREEN}Closed position {order_id}{Style.RESET_ALL}")
                            success_count += 1
                        else:
                            logger.info(f"{colored_time}: Failed to cancel order or close position {order_id}")
                except Exception as e:
                    logger.error(f"{colored_time}: Error processing order {order_id}: {e}")

            # If we successfully processed any orders, check if we should remove the message
            if success_count > 0:
                remaining_orders = await self.get_remaining_orders_count(matched_msg_id)
                if remaining_orders == 0:
                    self.order_cache.remove_message(matched_msg_id)
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}All orders processed, removed message {matched_msg_id} from cache{Style.RESET_ALL}")


        elif command_type == 'breakeven':
            # For breakeven command, use entry price from cache
            # Get the entry price from the cached data
            if not entry_price:
                logger.warning(f"{colored_time}: No entry price found in cache for message {matched_msg_id}")

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
            "message_id": matched_msg_id,
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

    def configure_content_matching(self, enabled=True, max_age_hours=24, debug=False):
        """Configure content matching behavior"""
        self.content_matching_enabled = enabled
        self.max_content_match_age = max_age_hours
        self.debug_mode = debug

        logger.info(f"Content matching {'enabled' if enabled else 'disabled'}, " +
                    f"max age: {max_age_hours} hours, debug mode: {'on' if debug else 'off'}")
        return True