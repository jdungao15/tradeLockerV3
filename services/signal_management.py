import re
import logging
import asyncio
import time
from datetime import datetime, timedelta
import json

import aiohttp
import pytz
from colorama import Fore, Style

logger = logging.getLogger(__name__)


class EnhancedSignalManagementHandler:
    """
    Enhanced handler for signal management instructions like "move to breakeven" or "close early"
    with proper use of TradeLocker API clients.
    """

    def __init__(self, accounts_client, orders_client, instruments_client, quotes_client, auth_client):
        self.accounts_client = accounts_client
        self.orders_client = orders_client
        self.instruments_client = instruments_client
        self.quotes_client = quotes_client
        self.auth = auth_client
        self.signal_history = {}  # Reference to missed signal handler's history
        self.message_logs = []  # Store logs of processed messages for debugging
        self.max_log_size = 200  # Maximum number of message logs to keep

        # Configuration options that can be modified based on risk profile
        self.auto_breakeven = True  # Whether to automatically move SL to breakeven
        self.auto_close_early = True  # Whether to automatically close positions when recommended
        self.confirmation_required = False  # Whether to ask for confirmation before actions
        self.partial_closure_percent = 30  # Percentage to close when partial closure is recommended

        # Timeframe for considering active orders as relevant (in hours)
        self.active_order_timeframe = 24  # Consider orders placed in last 24 hours

        # Debug mode for more verbose logging
        self.debug_mode = False

    def set_debug_mode(self, enabled=True):
        """Toggle debug mode for more verbose logging"""
        self.debug_mode = enabled
        logger.info(f"Debug mode {'enabled' if enabled else 'disabled'}")

    def set_risk_profile_settings(self, profile):
        """Configure behavior based on selected risk profile"""
        if profile == "conservative":
            self.auto_breakeven = False
            self.auto_close_early = False
            self.confirmation_required = True
            self.partial_closure_percent = 33  # Close 1/3

        elif profile == "balanced":
            self.auto_breakeven = True
            self.auto_close_early = False
            self.confirmation_required = True
            self.partial_closure_percent = 50  # Close half

        elif profile == "aggressive":
            self.auto_breakeven = True
            self.auto_close_early = True
            self.confirmation_required = False
            self.partial_closure_percent = 66  # Close 2/3

        logger.info(f"Signal management settings updated to {profile} profile:")
        logger.info(f"Auto-breakeven: {self.auto_breakeven}, Auto-close-early: {self.auto_close_early}")
        logger.info(
            f"Confirmation required: {self.confirmation_required}, Partial closure: {self.partial_closure_percent}%")

    def set_signal_history(self, signal_history):
        """Set reference to the signal history from missed signal handler"""
        self.signal_history = signal_history

    def log_message_for_debugging(self, msg_data):
        """Store message data for debugging purposes with timestamp"""
        msg_data['timestamp'] = datetime.now().isoformat()
        self.message_logs.append(msg_data)

        # Limit log size
        if len(self.message_logs) > self.max_log_size:
            self.message_logs = self.message_logs[-self.max_log_size:]

    def is_management_instruction(self, message, reply_to_msg_id=None):
        """
        Detect if a message contains trade management instructions

        Returns:
            tuple: (instruction_type, instrument, details) if instructions found
                   instruction_type can be: 'breakeven', 'close', 'partial_close', None
        """
        if not message:
            return None, None, None

        message_lower = message.lower()

        # Handle single-word commands first
        if message_lower.strip() == "breakeven" or message_lower.strip() == "be":
            logger.info(f"Detected simple breakeven command: {message}")
            return 'breakeven', None, {}

        if message_lower.strip() == "close" or message_lower.strip() == "cancel":
            logger.info(f"Detected simple close command: {message}")
            return 'close', None, {}

        # Check for breakeven instructions
        breakeven_patterns = [
            r"move\s+(?:sl|stop(?:\s+loss)?)\s+to\s+(?:be|b/?e|breakeven|entry)",
            r"sl\s+(?:to\s+)?(?:be|b/?e|breakeven|entry)",
            r"(?:be|b/?e|breakeven)\s+(?:your\s+|the\s+)?(?:sl|stop(?:\s+loss)?)",
            r"lock\s+(?:in\s+)?profits",
            r"secure\s+(?:your\s+)?profits"
        ]

        for pattern in breakeven_patterns:
            if re.search(pattern, message_lower):
                # Try to identify the instrument
                instrument = self._extract_instrument(message_lower)
                return 'breakeven', instrument, {}

        # Check for close instructions
        close_patterns = [
            r"close\s+(?:all|your|the)?\s+positions?",
            r"close\s+(?:all|your|the)?\s+trades?",
            r"exit\s+(?:all|your|the)?\s+positions?",
            r"exit\s+(?:all|your|the)?\s+trades?",
            r"take\s+(?:your\s+)?profits?",
            r"cancel\s+(?:all|your|the)?\s+orders?"
        ]

        for pattern in close_patterns:
            if re.search(pattern, message_lower):
                # Check for partial closure
                partial = "partial" in message_lower or "half" in message_lower or "some" in message_lower

                # Try to identify the instrument
                instrument = self._extract_instrument(message_lower)

                details = {'partial': partial}

                # If partial, check for specific percentage
                if partial:
                    percentage_match = re.search(r"(\d+)%", message_lower)
                    if percentage_match:
                        details['percentage'] = int(percentage_match.group(1))
                    elif "half" in message_lower:
                        details['percentage'] = 50
                    elif "third" in message_lower or "1/3" in message_lower:
                        details['percentage'] = 33
                    elif "two third" in message_lower or "2/3" in message_lower:
                        details['percentage'] = 66
                    else:
                        details['percentage'] = self.partial_closure_percent

                instruction_type = 'partial_close' if partial else 'close'
                return instruction_type, instrument, details

        return None, None, None

    def _extract_instrument(self, message):
        """Extract instrument name from message"""
        from utils.instrument_utils import extract_instrument_from_text

        # Use the centralized utility function to extract instrument
        return extract_instrument_from_text(message)

    async def find_matching_open_trades(self, account):
        """Find all currently open positions/trades using the proper client"""
        try:
            # Use the account client to get positions
            positions_response = await self.accounts_client.get_current_position_async(
                account['id'],
                account['accNum']
            )

            if not positions_response or 'd' not in positions_response or 'positions' not in positions_response['d']:
                return []

            open_positions = []

            for position in positions_response['d']['positions']:
                position_id = position[0]
                instrument_id = position[1]

                # Get instrument details using the instrument client
                position_instrument = await self.instruments_client.get_instrument_by_id_async(
                    account['id'],
                    account['accNum'],
                    instrument_id
                )

                if position_instrument:
                    open_positions.append({
                        'position_id': position_id,
                        'instrument_id': instrument_id,
                        'instrument_name': position_instrument.get('name'),
                        'side': position[3],
                        'quantity': position[4],
                        'entry_price': position[5]
                    })

            return open_positions

        except Exception as e:
            logger.error(f"Error finding open trades: {e}")
            return []

    async def find_matching_pending_orders(self, account, instrument=None):
        """
        Find all currently pending orders using the proper client with caching to reduce API calls

        Args:
            account: Account information
            instrument: Optional instrument name to filter by

        Returns:
            list: List of matching pending orders
        """
        try:
            # Use cache to reduce API calls (5 second cache for pending orders)
            cache_key = f"pending_orders:{account['id']}:{account['accNum']}"
            cache_time = getattr(self, '_pending_orders_cache_time', {}).get(cache_key, 0)
            cache_valid = (time.time() - cache_time) < 5  # Cache valid for 5 seconds

            if hasattr(self, '_pending_orders_cache') and cache_valid:
                # Use cached orders if available and recent
                all_pending_orders = self._pending_orders_cache.get(cache_key, [])
                logger.debug(f"Using cached pending orders ({len(all_pending_orders)} orders)")
            else:
                # Use the orders client to get orders - this respects rate limits in ApiClient
                orders_response = await self.orders_client.get_orders_async(
                    account['id'],
                    account['accNum']
                )

                if not orders_response or 'd' not in orders_response or 'orders' not in orders_response['d']:
                    return []

                all_pending_orders = []

                # Filter for pending orders
                for order in orders_response['d']['orders']:
                    if order[6] in ['New', 'PartiallyFilled', 'Accepted', 'Working']:
                        order_id = order[0]
                        instrument_id = order[1]

                        # Get instrument details using the instrument client
                        # We'll try to get instrument details from cache first
                        instrument_cache_key = f"instrument:{instrument_id}"
                        order_instrument = None

                        if hasattr(self, '_instrument_cache') and instrument_cache_key in self._instrument_cache:
                            order_instrument = self._instrument_cache.get(instrument_cache_key)
                        else:
                            # Get instrument details - with potential delay for rate limiting
                            order_instrument = await self.instruments_client.get_instrument_by_id_async(
                                account['id'],
                                account['accNum'],
                                instrument_id
                            )

                            # Cache the instrument details
                            if not hasattr(self, '_instrument_cache'):
                                self._instrument_cache = {}
                            if order_instrument:
                                self._instrument_cache[instrument_cache_key] = order_instrument

                        if order_instrument:
                            all_pending_orders.append({
                                'order_id': order_id,
                                'instrument_id': instrument_id,
                                'instrument_name': order_instrument.get('name'),
                                'side': order[4],
                                'quantity': order[3],
                                'price': order[9],
                                'type': order[5]  # market, limit, etc.
                            })

                # Cache the results for future use
                if not hasattr(self, '_pending_orders_cache'):
                    self._pending_orders_cache = {}
                if not hasattr(self, '_pending_orders_cache_time'):
                    self._pending_orders_cache_time = {}

                self._pending_orders_cache[cache_key] = all_pending_orders
                self._pending_orders_cache_time[cache_key] = time.time()

            # Filter by instrument if specified
            if instrument and all_pending_orders:
                # First try exact match
                matching_orders = [
                    order for order in all_pending_orders
                    if order.get('instrument_name') == instrument
                ]

                # If no exact matches, try normalized name
                if not matching_orders:
                    from utils.instrument_utils import normalize_instrument_name
                    normalized_instrument = normalize_instrument_name(instrument)

                    matching_orders = [
                        order for order in all_pending_orders
                        if normalize_instrument_name(order.get('instrument_name')) == normalized_instrument
                    ]

                return matching_orders

            return all_pending_orders

        except Exception as e:
            logger.error(f"Error finding pending orders: {e}")
            return []

    async def find_matching_positions(self, account, instrument=None):
        """Find currently open positions matching the instrument"""
        try:
            all_positions = await self.find_matching_open_trades(account)

            if not instrument:
                return all_positions

            # Filter by instrument if specified
            matching_positions = [
                pos for pos in all_positions
                if pos.get('instrument_name') == instrument
            ]

            if not matching_positions:
                # Try normalized instrument name comparison
                from utils.instrument_utils import normalize_instrument_name
                normalized_instrument = normalize_instrument_name(instrument)

                matching_positions = [
                    pos for pos in all_positions
                    if normalize_instrument_name(pos.get('instrument_name')) == normalized_instrument
                ]

            return matching_positions

        except Exception as e:
            logger.error(f"Error finding matching positions: {e}")
            return []

    async def find_matching_signal_from_content(self, message, instrument=None):
        """
        Find a matching signal based on message content rather than reply ID

        This is the core of the enhanced content-based matching
        """
        if not self.signal_history:
            return None, None

        # If instrument is specified, only check signals for that instrument
        instruments_to_check = [instrument] if instrument else list(self.signal_history.keys())

        # Extract potential identifiers from the message
        message_lower = message.lower()

        # Look for price mentions that might help identify the signal
        price_mentions = re.findall(r'\b\d+\.\d+\b', message_lower)
        entry_price_mention = None
        if "entry" in message_lower and price_mentions:
            # Try to find entry price mention
            entry_match = re.search(r'entry\s+(?:at|@|price)?\s*:?\s*(\d+\.\d+)', message_lower)
            if entry_match:
                entry_price_mention = float(entry_match.group(1))

        # Extract order direction mention if present
        direction_mention = None
        if "buy" in message_lower:
            direction_mention = "buy"
        elif "sell" in message_lower:
            direction_mention = "sell"

        # Look for signal timestamp/time mentions
        # Traders often reference "the signal from 2 hours ago" or similar
        time_references = []
        time_patterns = [
            r'(\d+)\s*(?:hour|hr)s?\s+ago',
            r'(\d+)\s*(?:minute|min)s?\s+ago',
            r'today\s+at\s+(\d+:\d+)',
            r'signal\s+from\s+(\d+:\d+)'
        ]

        for pattern in time_patterns:
            time_match = re.search(pattern, message_lower)
            if time_match:
                time_references.append(time_match.group(1))

        best_match = None
        best_score = 0
        best_instrument = None

        # Start searching through signals
        for instr in instruments_to_check:
            if instr not in self.signal_history:
                continue

            signals = self.signal_history[instr]

            for signal in signals:
                # Calculate match score for this signal
                score = 0

                # Prefer recent signals (within last 24 hours)
                signal_timestamp = signal.get('timestamp')
                if signal_timestamp:
                    age_hours = (datetime.now(pytz.UTC) - signal_timestamp).total_seconds() / 3600
                    if age_hours < 24:
                        score += 10 - min(10, age_hours)  # More recent = higher score

                # Match entry price if mentioned
                if entry_price_mention and 'entry_price' in signal:
                    try:
                        signal_entry = float(signal['entry_price'])
                        # If entry prices are within 0.5% of each other
                        if abs(signal_entry - entry_price_mention) / signal_entry < 0.005:
                            score += 20  # Strong indicator of a match
                    except (ValueError, TypeError):
                        pass

                # Match order direction if mentioned
                if direction_mention and signal.get('order_type', '').lower() == direction_mention:
                    score += 15

                # Match price mentions against take profits and stop loss
                if price_mentions:
                    # Check against take profits
                    for tp in signal.get('take_profits', []):
                        if any(abs(float(tp) - float(pm)) < 0.1 for pm in price_mentions):
                            score += 10

                    # Check against stop loss
                    stop_loss = signal.get('stop_loss')
                    if stop_loss and any(abs(float(stop_loss) - float(pm)) < 0.1 for pm in price_mentions):
                        score += 10

                # Check if raw message content is similar
                if signal.get('raw_message') and message_lower:
                    # Simple text overlap check
                    raw_message = signal.get('raw_message', '').lower()
                    common_words = set(raw_message.split()).intersection(set(message_lower.split()))
                    if len(common_words) > 5:  # If they share significant common words
                        score += min(10, len(common_words))

                # Store best match
                if score > best_score:
                    best_score = score
                    best_match = signal
                    best_instrument = instr

        # Only consider it a match if score is significant
        if best_score >= 15:
            return best_match, best_instrument

        return None, None

    async def find_most_likely_position(self, account, message):
        """
        Find the most likely position based on message content
        without relying on explicit instrument mention
        """
        # Get all currently open positions
        all_positions = await self.find_matching_open_trades(account)
        if not all_positions:
            return None

        message_lower = message.lower()

        # Extract potential identifiers from the message
        price_mentions = re.findall(r'\b\d+\.\d+\b', message_lower)

        # Check for mentions of buy/sell
        is_buy_mentioned = "buy" in message_lower
        is_sell_mentioned = "sell" in message_lower

        best_match = None
        best_score = 0

        for position in all_positions:
            score = 0
            instrument_name = position.get('instrument_name', '').lower()

            # Check if instrument is mentioned in message
            if instrument_name in message_lower:
                score += 20
            elif len(instrument_name) >= 6:  # For longer instrument names like EURUSD
                for part in instrument_name.split('.'):  # Handle suffix like .C
                    if part and part in message_lower:
                        score += 15
                        break

            # Check if position side matches direction mentioned in message
            position_side = position.get('side', '').lower()
            if (position_side == 'buy' and is_buy_mentioned) or (position_side == 'sell' and is_sell_mentioned):
                score += 10

            # Check if entry price is mentioned
            entry_price = float(position.get('entry_price', 0))
            if entry_price > 0 and price_mentions:
                for price_str in price_mentions:
                    try:
                        price = float(price_str)
                        # If price is within 1% of entry price
                        if abs(price - entry_price) / entry_price < 0.01:
                            score += 15
                    except ValueError:
                        continue

            # Store best match
            if score > best_score:
                best_score = score
                best_match = position

        # Only consider it a likely match if score is significant
        if best_score >= 25:
            return best_match

        return None

    async def modify_position_sl_to_breakeven(self, account, position, buffer_pips=2):
        """
        Move stop loss to breakeven (entry price) with optional buffer

        Args:
            account: Account information
            position: Position information dict
            buffer_pips: Number of pips away from entry for safety
        """
        try:
            position_id = position['position_id']
            entry_price = float(position['entry_price'])
            side = position['side'].lower()

            # Get instrument details to determine pip size
            instrument = await self.instruments_client.get_instrument_by_id_async(
                account['id'],
                account['accNum'],
                position['instrument_id']
            )

            if not instrument:
                logger.error(f"Could not find instrument for position {position_id}")
                return False

            # Determine pip size
            instrument_name = instrument['name']
            if instrument_name.endswith('JPY'):
                pip_size = 0.01
            elif instrument_name == 'XAUUSD':
                pip_size = 0.1
            elif instrument_name in ['DJI30', 'NDX100']:
                pip_size = 1.0
            else:
                pip_size = 0.0001

            # Calculate buffer in price terms
            buffer_amount = buffer_pips * pip_size

            # Calculate new stop loss price with buffer
            if side == 'buy':
                # For buy, SL is below entry
                new_sl = entry_price - buffer_amount
            else:
                # For sell, SL is above entry
                new_sl = entry_price + buffer_amount

            # Format the new SL to match instrument precision
            # For simplicity we're using a fixed precision here
            new_sl = round(new_sl, 5)

            # Update the stop loss - Direct API call since there's no client method
            url = f"{self.auth.base_url}/trade/positions/{position_id}"
            headers = {
                "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                "accNum": str(account['accNum']),
                "Content-Type": "application/json"
            }
            body = {"stopLoss": new_sl}

            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=body) as response:
                    if response.status == 200:
                        logger.info(f"Successfully moved SL to breakeven for position {position_id}: {new_sl}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Failed to update SL for position {position_id}: {response.status} - {error_text}")
                        return False

        except Exception as e:
            logger.error(f"Error moving SL to breakeven: {e}")
            return False

    async def close_position(self, account, position, percentage=100):
        """
        Close position fully or partially

        Args:
            account: Account information
            position: Position information dict
            percentage: Percentage of position to close (default 100% = full closure)
        """
        try:
            position_id = position['position_id']

            if percentage < 100:
                # For partial closure, calculate the quantity to close
                full_quantity = float(position['quantity'])
                close_quantity = full_quantity * (percentage / 100)

                # Trade API often requires specific lot sizes, so we need to round appropriately
                # This depends on the broker's requirements - here's a basic approach:
                if full_quantity >= 1.0:
                    close_quantity = round(close_quantity, 1)  # Round to 0.1 lots
                else:
                    close_quantity = round(close_quantity, 2)  # Round to 0.01 lots

                # Ensure minimum quantity
                close_quantity = max(close_quantity, 0.01)

                # Create the close request with quantity
                url = f"{self.auth.base_url}/trade/positions/{position_id}/close"
                headers = {
                    "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                    "accNum": str(account['accNum']),
                    "Content-Type": "application/json"
                }
                body = {"qty": close_quantity}

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=body) as response:
                        if response.status == 200:
                            logger.info(f"Successfully closed {percentage}% of position {position_id}")
                            return True
                        else:
                            error_text = await response.text()
                            logger.error(
                                f"Failed to partially close position {position_id}: {response.status} - {error_text}")
                            return False
            else:
                # For full closure, use the close endpoint without quantity
                url = f"{self.auth.base_url}/trade/positions/{position_id}/close"
                headers = {
                    "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                    "accNum": str(account['accNum']),
                    "Content-Type": "application/json"
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers) as response:
                        if response.status == 200:
                            logger.info(f"Successfully closed position {position_id}")
                            return True
                        else:
                            error_text = await response.text()
                            logger.error(f"Failed to close position {position_id}: {response.status} - {error_text}")
                            return False

        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return False

    async def cancel_order(self, account, order_id):
        """
        Cancel a pending order - Properly using the orders client

        Args:
            account: Account information
            order_id: Order ID to cancel

        Returns:
            bool: Success status
        """
        try:
            # Use the orders_client to cancel the order
            result = await self.orders_client.cancel_order_async(
                account['id'],
                account['accNum'],
                order_id
            )

            if result:
                logger.info(f"Successfully cancelled order {order_id}")
                return True
            else:
                logger.error(f"Failed to cancel order {order_id}")
                return False

        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def handle_management_instruction(self, account, instruction_type, instrument, details, colored_time,
                                            signal_id=None):
        """
        Execute the management instruction based on its type, with rate limit handling and signal filtering

        Args:
            account: Account information
            instruction_type: Type of instruction ('breakeven', 'close', 'partial_close')
            instrument: Instrument name or None for all positions
            details: Additional details for the instruction
            colored_time: Formatted time for logging
            signal_id: Optional signal ID to filter by (for close/cancel commands)

        Returns:
            bool: Success status
        """
        # Check if auto-management is enabled for this type
        if instruction_type == 'breakeven' and not self.auto_breakeven:
            logger.info(
                f"{colored_time}: Breakeven instruction detected but auto-breakeven is disabled in current profile")
            return False

        if (instruction_type == 'close' or instruction_type == 'partial_close') and not self.auto_close_early:
            logger.info(f"{colored_time}: Close instruction detected but auto-close is disabled in current profile")
            return False

        # For 'close' or 'cancel' instructions, we need to check both positions AND pending orders
        if instruction_type == 'close':
            # First, check for open positions
            positions = await self.find_matching_positions(account, instrument)

            # Add a small delay before checking orders to avoid rate limiting
            await asyncio.sleep(1.1)  # Just over 1 second to respect position vs order rate limits

            # Then, check for pending orders
            all_pending_orders = await self.find_matching_pending_orders(account, instrument)

            # If we have a specific signal ID, filter orders to only include those from this signal
            pending_orders = all_pending_orders
            if signal_id:
                filtered_orders = []

                # Check each order to see if it's associated with this signal
                for order in all_pending_orders:
                    is_from_signal = False

                    # Look for this order in the signal history
                    if instrument in self.signal_history:
                        for signal in self.signal_history[instrument]:
                            if signal.get('signal_id') == signal_id:
                                if order['order_id'] in signal.get('related_orders', []):
                                    filtered_orders.append(order)
                                    is_from_signal = True
                                    break

                pending_orders = filtered_orders
                logger.info(
                    f"{colored_time}: Filtered {len(all_pending_orders)} pending orders to {len(pending_orders)} orders for signal {signal_id}")

            # Log what we found
            if signal_id:
                logger.info(
                    f"{colored_time}: Found {len(positions)} open positions and {len(pending_orders)} pending orders for signal {signal_id} ({instrument})")
            else:
                logger.info(
                    f"{colored_time}: Found {len(positions)} open positions and {len(pending_orders)} pending orders for {instrument if instrument else 'all instruments'}")

            # If we have neither positions nor pending orders, nothing to do
            if not positions and not pending_orders:
                if signal_id:
                    logger.info(
                        f"{colored_time}: No matching positions or pending orders found for signal {signal_id} ({instrument})")
                else:
                    logger.info(
                        f"{colored_time}: No matching positions or pending orders found for {instrument if instrument else 'any instrument'}")
                return False

            # For confirmation if required
            if self.confirmation_required:
                position_text = f"{len(positions)} positions" if positions else "0 positions"
                order_text = f"{len(pending_orders)} pending orders" if pending_orders else "0 pending orders"

                if instruction_type == 'close':
                    signal_text = f" for signal {signal_id}" if signal_id else ""
                    confirmation = input(
                        f"{Fore.RED}Close/cancel {position_text} and {order_text}{signal_text}? (y/n): {Style.RESET_ALL}")
                    if confirmation.lower() != 'y':
                        logger.info(f"{colored_time}: Close operation cancelled by user")
                        return False
                elif instruction_type == 'partial_close':
                    percentage = details.get('percentage', self.partial_closure_percent)
                    confirmation = input(
                        f"{Fore.YELLOW}Close {percentage}% of {position_text}? (y/n): {Style.RESET_ALL}")
                    if confirmation.lower() != 'y':
                        logger.info(f"{colored_time}: Partial close operation cancelled by user")
                        return False

            # Execute the appropriate action for each position and order
            success_count = 0
            total_count = len(positions) + len(pending_orders)

            # Handle open positions
            for position in positions:
                if instruction_type == 'close':
                    result = await self.close_position(account, position)
                    if result:
                        success_count += 1
                        logger.info(
                            f"{colored_time}: {Fore.RED}Closed position {position['position_id']}{Style.RESET_ALL}")
                elif instruction_type == 'partial_close':
                    percentage = details.get('percentage', self.partial_closure_percent)
                    result = await self.close_position(account, position, percentage)
                    if result:
                        success_count += 1
                        logger.info(
                            f"{colored_time}: {Fore.YELLOW}Closed {percentage}% of position {position['position_id']}{Style.RESET_ALL}")

            # Add delay before handling orders to avoid rate limits
            if positions and pending_orders:
                await asyncio.sleep(1.1)  # Delay to respect rate limits between position and order operations

            # Handle pending orders with rate limiting between each cancel
            for i, order in enumerate(pending_orders):
                # For pending orders, we need to cancel them
                try:
                    order_id = order['order_id']

                    # Add a small delay between cancel operations to avoid rate limiting
                    if i > 0:
                        await asyncio.sleep(1.1)  # Respect API rate limits between cancellations

                    result = await self.cancel_order(account, order_id)
                    if result:
                        success_count += 1
                        signal_text = f" from signal {signal_id}" if signal_id else ""
                        logger.info(
                            f"{colored_time}: {Fore.RED}Cancelled pending order {order_id}{signal_text}{Style.RESET_ALL}")

                        # Log the cancellation with signal information for debugging
                        if signal_id:
                            logger.info(f"{colored_time}: Cancelled pending order {order_id} from signal {signal_id}")
                except Exception as e:
                    logger.error(f"Error cancelling order: {e}")

            # Return overall success
            if success_count > 0:
                signal_text = f" for signal {signal_id}" if signal_id else ""
                logger.info(
                    f"{colored_time}: Successfully managed {success_count} out of {total_count} positions/orders{signal_text}")
                return True
            else:
                logger.warning(f"{colored_time}: Failed to manage any positions/orders")
                return False

        # For breakeven instructions, we only care about open positions
        elif instruction_type == 'breakeven':
            positions = await self.find_matching_positions(account, instrument)

            if not positions:
                logger.info(
                    f"{colored_time}: No matching positions found for {instrument if instrument else 'any instrument'}")
                return False

            if self.confirmation_required:
                confirmation = input(
                    f"{Fore.YELLOW}Move stop loss to breakeven for {len(positions)} positions? (y/n): {Style.RESET_ALL}")
                if confirmation.lower() != 'y':
                    logger.info(f"{colored_time}: Breakeven operation cancelled by user")
                    return False

            # Execute breakeven action on positions with rate limiting
            success_count = 0
            for i, position in enumerate(positions):
                # Add delay between operations to respect rate limits
                if i > 0:
                    await asyncio.sleep(1.1)  # Respect rate limits between position operations

                result = await self.modify_position_sl_to_breakeven(account, position)
                if result:
                    success_count += 1
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}Moved SL to breakeven for position {position['position_id']}{Style.RESET_ALL}")

            # Return overall success
            if success_count > 0:
                logger.info(
                    f"{colored_time}: Successfully moved SL to breakeven for {success_count} out of {len(positions)} positions")
                return True
            else:
                logger.warning(f"{colored_time}: Failed to move SL to breakeven for any positions")
                return False

        return False

    async def handle_message(self, message, account, colored_time, reply_to_msg_id=None):
        """
        Enhanced main handler that filters orders by specific signal ID
        """
        # Log message for debugging (regardless of whether it's a management instruction)
        message_log = {
            'message': message,
            'reply_to_msg_id': reply_to_msg_id,
            'is_management': False
        }

        # Check if this is a management instruction
        instruction_type, instrument_from_message, details = self.is_management_instruction(message, reply_to_msg_id)

        if not instruction_type:
            self.log_message_for_debugging(message_log)
            return False, None

        # Update log with management instruction details
        message_log['is_management'] = True
        message_log['instruction_type'] = instruction_type
        message_log['instrument'] = instrument_from_message
        message_log['details'] = details

        # Log the detected instruction
        instruction_color = Fore.CYAN if instruction_type == 'breakeven' else (
            Fore.RED if instruction_type == 'close' else Fore.YELLOW)
        logger.info(f"{colored_time}: {instruction_color}Detected {instruction_type} instruction{Style.RESET_ALL}" +
                    (f" for {instrument_from_message}" if instrument_from_message else ""))

        # ----- STAGE 1: IDENTIFY TARGET INSTRUMENT AND SIGNAL -----
        target_instrument = None
        identification_method = None
        target_signal_id = None  # Track which signal this is replying to

        # Approach 1: Instrument directly mentioned in message
        if instrument_from_message:
            target_instrument = instrument_from_message
            identification_method = "direct_instrument"
            logger.info(f"{colored_time}: Using instrument {target_instrument} directly mentioned in message")

        # Approach 2: Find via reply_to_msg_id if available
        elif reply_to_msg_id:
            # Try to find the original signal from the reply_to_msg_id
            for instr, signals in self.signal_history.items():
                for signal in signals:
                    if signal.get('signal_id') == reply_to_msg_id:
                        target_instrument = instr
                        target_signal_id = reply_to_msg_id  # Store the specific signal ID
                        identification_method = "reply_id_match"
                        logger.info(
                            f"{colored_time}: Found instrument {target_instrument} via reply_id {reply_to_msg_id}")
                        break
                if target_instrument:
                    break

        # ----- STAGE 2: EXECUTE MANAGEMENT ACTION WITH PROPER FILTERING -----
        if target_instrument:
            # Execute the instruction using proper client methods, but filtered by signal ID
            message_log['match_method'] = identification_method
            message_log['instrument'] = target_instrument
            message_log['signal_id'] = target_signal_id  # Add signal ID to log
            self.log_message_for_debugging(message_log)

            # Special handling for close/cancel when we have a specific signal ID
            if instruction_type == 'close' and target_signal_id:
                # Get pending orders
                all_pending_orders = await self.find_matching_pending_orders(account, target_instrument)

                # Get matching positions
                positions = await self.find_matching_positions(account, target_instrument)

                # Filter pending orders to only include those associated with this specific signal
                # This requires that order registration is properly tracking which signal each order belongs to
                signal_pending_orders = []
                other_pending_orders = []

                for order in all_pending_orders:
                    # Check if this order is registered with the target signal
                    is_from_signal = False

                    # Look up in signal history to see if this order ID is registered with this signal
                    if target_instrument in self.signal_history:
                        for signal in self.signal_history[target_instrument]:
                            if signal.get('signal_id') == target_signal_id:
                                if order['order_id'] in signal.get('related_orders', []):
                                    signal_pending_orders.append(order)
                                    is_from_signal = True
                                    break

                    if not is_from_signal:
                        other_pending_orders.append(order)

                # Log what we found
                logger.info(
                    f"{colored_time}: Found {len(positions)} open positions, {len(signal_pending_orders)} pending orders for signal {target_signal_id}, and {len(other_pending_orders)} other pending orders for {target_instrument}")

                # Cancel only orders related to this specific signal
                success_count = 0

                # Only attempt to cancel if we found orders for this signal
                if signal_pending_orders:
                    for order in signal_pending_orders:
                        order_id = order['order_id']
                        result = await self.cancel_order(account, order_id)
                        if result:
                            success_count += 1
                            logger.info(
                                f"{colored_time}: {Fore.RED}Cancelled pending order {order_id} from signal {target_signal_id}{Style.RESET_ALL}")

                    if success_count > 0:
                        logger.info(
                            f"{colored_time}: Successfully cancelled {success_count} out of {len(signal_pending_orders)} orders for signal {target_signal_id}")
                        return True, {
                            "instruction_type": instruction_type,
                            "instrument": target_instrument,
                            "details": details,
                            "success": True,
                            "match_method": identification_method,
                            "signal_id": target_signal_id,
                            "orders_cancelled": success_count
                        }
                    else:
                        logger.warning(f"{colored_time}: Failed to cancel any orders for signal {target_signal_id}")
                else:
                    logger.info(f"{colored_time}: No pending orders found specifically for signal {target_signal_id}")

                    # If we have positions, try to close those instead
                    if positions:
                        # Fall through to normal position handling
                        pass
                    else:
                        logger.warning(f"{colored_time}: No positions or orders found for signal {target_signal_id}")
                        return True, {
                            "instruction_type": instruction_type,
                            "instrument": target_instrument,
                            "details": details,
                            "success": False,
                            "match_method": identification_method,
                            "signal_id": target_signal_id,
                            "reason": "no_matching_orders_or_positions"
                        }

            # Default handling for all other cases
            result = await self.handle_management_instruction(
                account, instruction_type, target_instrument, details, colored_time, target_signal_id
            )

            return True, {
                "instruction_type": instruction_type,
                "instrument": target_instrument,
                "details": details,
                "success": result,
                "match_method": identification_method,
                "signal_id": target_signal_id
            }

        # ----- STAGE 3: CONTENT-BASED MATCHING (FALLBACKS) -----

        # Approach 3: Try content-based matching with signal history
        matching_signal, matching_instrument = await self.find_matching_signal_from_content(message)

        if matching_signal and matching_instrument:
            logger.info(
                f"{colored_time}: {Fore.GREEN}Matched instruction to signal content for {matching_instrument}{Style.RESET_ALL}")

            message_log['match_method'] = 'content_match'
            message_log['matched_signal_id'] = matching_signal.get('signal_id')
            message_log['instrument'] = matching_instrument
            self.log_message_for_debugging(message_log)

            # Execute the instruction
            result = await self.handle_management_instruction(
                account, instruction_type, matching_instrument, details, colored_time
            )
            return True, {
                "instruction_type": instruction_type,
                "instrument": matching_instrument,
                "details": details,
                "success": result,
                "match_method": "content_match"
            }

        # Approach 4: Try to identify the most likely position based on message content
        most_likely_position = await self.find_most_likely_position(account, message)

        if most_likely_position:
            likely_instrument = most_likely_position.get('instrument_name')
            logger.info(
                f"{colored_time}: {Fore.GREEN}Identified most likely position for {likely_instrument} based on message content{Style.RESET_ALL}")

            message_log['match_method'] = 'position_match'
            message_log['position_id'] = most_likely_position.get('position_id')
            message_log['instrument'] = likely_instrument
            self.log_message_for_debugging(message_log)

            # Execute the instruction
            result = await self.handle_management_instruction(
                account, instruction_type, likely_instrument, details, colored_time
            )
            return True, {
                "instruction_type": instruction_type,
                "instrument": likely_instrument,
                "details": details,
                "success": result,
                "match_method": "position_match"
            }

        # Approach 5: If only one instrument position is open, assume that's the target
        all_positions = await self.find_matching_open_trades(account)
        unique_instruments = set(pos.get('instrument_name') for pos in all_positions)

        if len(unique_instruments) == 1:
            only_instrument = next(iter(unique_instruments))
            logger.info(
                f"{colored_time}: {Fore.GREEN}Only one instrument ({only_instrument}) has open positions, assuming instruction applies to it{Style.RESET_ALL}")

            message_log['match_method'] = 'single_instrument'
            message_log['instrument'] = only_instrument
            self.log_message_for_debugging(message_log)

            # Execute the instruction
            result = await self.handle_management_instruction(
                account, instruction_type, only_instrument, details, colored_time
            )
            return True, {
                "instruction_type": instruction_type,
                "instrument": only_instrument,
                "details": details,
                "success": result,
                "match_method": "single_instrument"
            }

        # No matching instrument could be determined
        logger.warning(
            f"{colored_time}: {Fore.YELLOW}Could not determine target instrument for the {instruction_type} instruction{Style.RESET_ALL}")

        message_log['match_method'] = 'no_match'
        self.log_message_for_debugging(message_log)

        return True, {
            "instruction_type": instruction_type,
            "instrument": None,
            "details": details,
            "success": False,
            "match_method": "no_match"
        }

    def export_message_logs(self, limit=None):
        """Export message logs for debugging/analysis"""
        logs_to_export = self.message_logs
        if limit:
            logs_to_export = logs_to_export[-limit:]

        return json.dumps(logs_to_export, indent=2)