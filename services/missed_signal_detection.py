import re
import logging
import asyncio
from datetime import datetime

import aiohttp
import pytz
from colorama import Fore, Style

logger = logging.getLogger(__name__)


class MissedSignalHandler:
    """
    Handles detection and management of missed trading signals
    based on TP hit messages from signal providers.
    """

    def __init__(self, accounts_client, orders_client, instruments_client, auth_client):
        self.accounts_client = accounts_client
        self.orders_client = orders_client
        self.instruments_client = instruments_client
        self.auth = auth_client  # Add this line
        self.signal_history = {}  # Store recent signals for matching
        self.max_history_size = 50  # Maximum number of signals to keep in history

        # Configuration options
        self.enable_fallback_protection = False  # Default to disabled for safety
        self.max_signal_age_hours = 12  # Only consider signals from last 48 hours
        self.consider_channel_source = True  # Consider channel/provider when matching

    def is_tp_hit_message(self, message, message_id=None):
        """
        Detect if the message indicates a take profit hit.

        Args:
            message (str): The message text to analyze
            message_id (str): Optional Telegram message ID

        Returns:
            tuple: (is_tp_hit, instrument, tp_level, tp_price, signal_hint) if it's a TP hit message
        """
        # Convert message to lowercase for case-insensitive matching
        message_lower = message.lower()

        # Common phrases that indicate TP hit
        tp_indicators = [
            r"tp\s*1\s*hit",  # Matches exactly "tp1 hit" with variations in spacing
            r"tp1\s+hit",  # Matches "tp1 hit" with at least one space
            r"tp1\s+HIT",  # Matches "tp1 HIT" with uppercase HIT
            r"tp\s*[1-3]\s*hit",  # Original pattern for tp1-3 hit
            r"tp\s*[1-3]\s*hit",
            r"take\s*profit\s*[1-3]\s*hit",
            r"target\s*[1-3]\s*hit",
            r"secured\s*[1-3]\s*at\s*tp",
            r"tp\s*[1-3]\s*reached",
            r"take\s*profit\s*[1-3]\s*reached",
            r"closed\s*[1-3]\s*at\s*profit"
        ]

        # Check for TP hit indicators
        is_tp_hit = any(re.search(pattern, message_lower) for pattern in tp_indicators)

        if not is_tp_hit:
            return False, None, None, None, None

        # Extract TP level (1, 2, or 3)
        tp_level = None
        for pattern in [r"tp\s*([1-3])", r"target\s*([1-3])", r"profit\s*([1-3])"]:
            match = re.search(pattern, message_lower)
            if match:
                tp_level = int(match.group(1))
                break

        # Try to extract the instrument from the message
        instrument_patterns = [
            # Common forex pairs
            r"(eur/?usd)",
            r"(gbp/?usd)",
            r"(usd/?jpy)",
            r"(aud/?usd)",
            r"(usd/?cad)",
            r"(nzd/?usd)",
            r"(usd/?chf)",
            # Commodities
            r"(gold|xauusd)",
            r"(silver|xagusd)",
            # Indices
            r"(dji30|us30)",
            r"(ndx100|nas100)"
        ]

        instrument = None
        for pattern in instrument_patterns:
            match = re.search(pattern, message_lower)
            if match:
                # Normalize instrument name
                instr = match.group(1).upper()

                # Handle aliases and formatting
                if instr == "GOLD":
                    instr = "XAUUSD"
                elif instr == "SILVER":
                    instr = "XAGUSD"
                elif instr == "US30":
                    instr = "DJI30"
                elif instr == "NAS100":
                    instr = "NDX100"

                # Remove slash if present
                instr = instr.replace("/", "")
                instrument = instr
                break

        # Try to extract the TP price (useful for matching with correct signal)
        tp_price = None
        price_patterns = [
            r"@\s*(\d+\.?\d*)",  # @1.2345
            r"at\s*(\d+\.?\d*)",  # at 1.2345
            r"price\s*:?\s*(\d+\.?\d*)",  # price: 1.2345
            r"tp\s*[1-3]\s*:?\s*(\d+\.?\d*)"  # TP1: 1.2345
        ]

        for pattern in price_patterns:
            match = re.search(pattern, message_lower)
            if match:
                try:
                    tp_price = float(match.group(1))
                    break
                except ValueError:
                    pass

        # Try to extract signal identifiers or other hints
        signal_hint = None
        # Look for signal IDs, timestamps, or other unique identifiers
        id_patterns = [
            r"signal\s*id\s*:?\s*([a-zA-Z0-9_-]+)",  # Signal ID: ABC123
            r"ref\s*:?\s*([a-zA-Z0-9_-]+)",  # Ref: ABC123
            r"entry\s*:?\s*(\d+\.?\d*)",  # Entry: 1.2345 (use entry price as hint)
        ]

        for pattern in id_patterns:
            match = re.search(pattern, message_lower)
            if match:
                signal_hint = match.group(1)
                break

        return is_tp_hit, instrument, tp_level, tp_price, signal_hint

    def add_signal_to_history(self, parsed_signal, message_id=None, raw_message=None, channel_id=None,
                              channel_name=None):
        """
        Add a signal to the history for later reference.

        Args:
            parsed_signal (dict): The parsed signal information
            message_id (str): Optional Telegram message ID for correlation
            raw_message (str): Optional raw message text for better matching
            channel_id (int/str): Optional ID of the channel/source
            channel_name (str): Optional name of the channel/source
        """
        if not parsed_signal or 'instrument' not in parsed_signal:
            return

        instrument = parsed_signal['instrument']
        timestamp = datetime.now(pytz.UTC)

        # Generate a signal ID if none provided
        signal_id = message_id or f"{instrument}-{timestamp.timestamp()}"

        # Create or update entry for this instrument
        if instrument not in self.signal_history:
            self.signal_history[instrument] = []

        # Create signal object with more details for better matching
        signal_obj = {
            'signal_id': signal_id,
            'timestamp': timestamp,
            'signal': parsed_signal,
            'entry_price': parsed_signal.get('entry_point'),
            'stop_loss': parsed_signal.get('stop_loss'),
            'take_profits': parsed_signal.get('take_profits', []),
            'order_type': parsed_signal.get('order_type'),
            'raw_message': raw_message,
            'related_orders': [],  # Will store order IDs when orders are placed
            'channel_id': channel_id,
            'channel_name': channel_name
        }

        # Add new signal
        self.signal_history[instrument].append(signal_obj)

        # Limit history size per instrument
        if len(self.signal_history[instrument]) > 10:
            self.signal_history[instrument] = self.signal_history[instrument][-10:]

        # Limit overall history size
        if sum(len(signals) for signals in self.signal_history.values()) > self.max_history_size:
            # Remove oldest signals first
            oldest_instrument = None
            oldest_timestamp = None

            for instr, signals in self.signal_history.items():
                if signals and (oldest_timestamp is None or signals[0]['timestamp'] < oldest_timestamp):
                    oldest_instrument = instr
                    oldest_timestamp = signals[0]['timestamp']

            if oldest_instrument and self.signal_history[oldest_instrument]:
                self.signal_history[oldest_instrument].pop(0)

        return signal_id  # Return the signal ID for reference

    def register_orders_for_signal(self, instrument, signal_id, order_ids):
        """
        Register order IDs with a particular signal for tracking.

        Args:
            instrument (str): The instrument name
            signal_id (str): The signal ID to associate with
            order_ids (list): List of order IDs placed for this signal
        """
        if instrument not in self.signal_history:
            return False

        # Find the signal by ID
        for signal in self.signal_history[instrument]:
            if signal.get('signal_id') == signal_id:
                signal['related_orders'] = order_ids
                logger.info(f"Registered {len(order_ids)} orders with signal {signal_id} for {instrument}")
                return True

        return False

    def find_matching_signal(self, instrument, tp_level, tp_price=None, signal_hint=None):
        """
        Find a matching signal based on various parameters.

        Args:
            instrument (str): Instrument name
            tp_level (int): Take profit level (1, 2, or 3)
            tp_price (float): Optional price at TP level
            signal_hint (str): Optional signal identifier hint

        Returns:
            tuple: (signal_obj, signal_id, matched_orders)
        """
        if instrument not in self.signal_history:
            return None, None, []

        # Get signals for this instrument, newest first (we want most recent matches)
        signals = sorted(
            self.signal_history[instrument],
            key=lambda x: x['timestamp'],
            reverse=True
        )

        for signal in signals:
            signal_obj = signal.get('signal', {})
            take_profits = signal_obj.get('take_profits', [])

            # Skip signals without take profits
            if not take_profits or len(take_profits) < tp_level:
                continue

            # If we have a TP price, check if it matches (with small tolerance)
            if tp_price is not None and take_profits:
                expected_tp = take_profits[tp_level - 1] if tp_level <= len(take_profits) else None

                if expected_tp:
                    # Use a small tolerance (e.g., 0.1%) for price comparison
                    tolerance = expected_tp * 0.001
                    if abs(expected_tp - tp_price) <= tolerance:
                        # Strong match based on price!
                        return signal, signal.get('signal_id'), signal.get('related_orders', [])

            # If we have a signal hint, try to match it
            if signal_hint:
                # Match against various stored properties
                if (str(signal.get('signal_id')) == str(signal_hint) or
                        (signal.get('entry_price') and str(signal.get('entry_price')) == str(signal_hint))):
                    return signal, signal.get('signal_id'), signal.get('related_orders', [])

            # Check raw message content for similarity
            if signal.get('raw_message') and signal_hint:
                if signal_hint in signal.get('raw_message', ''):
                    return signal, signal.get('signal_id'), signal.get('related_orders', [])

            # If we have orders associated with this signal, return it
            # This is a weaker match, but better than nothing
            if signal.get('related_orders'):
                return signal, signal.get('signal_id'), signal.get('related_orders', [])

        # No strong match found, return None
        return None, None, []

    def is_signal_from_same_source(self, signal, channel_id):
        """Check if a signal is from the same source/channel"""
        if not self.consider_channel_source:
            return True  # If feature disabled, all sources match

        if channel_id is None or signal.get('channel_id') is None:
            return True  # If we don't have channel info, assume match

        return str(signal.get('channel_id')) == str(channel_id)

    def is_signal_recent(self, signal):
        """Check if a signal is recent enough to be considered"""
        if self.max_signal_age_hours <= 0:
            return True  # No time limit

        now = datetime.now(pytz.UTC)
        signal_time = signal.get('timestamp')

        if not signal_time:
            return True  # No timestamp, assume recent

        # Check if signal is within the configured time window
        age_hours = (now - signal_time).total_seconds() / 3600
        return age_hours <= self.max_signal_age_hours

    async def has_open_positions(self, account, instrument_name):
        """
        Check if there are any open positions for the specified instrument.

        Args:
            account (dict): Account information
            instrument_name (str): Name of the instrument to check

        Returns:
            bool: True if open positions exist, False otherwise
        """
        try:
            # Get instrument ID first
            instrument = await self.instruments_client.get_instrument_by_name_async(
                account['id'],
                account['accNum'],
                instrument_name
            )

            if not instrument:
                logger.warning(f"Instrument {instrument_name} not found")
                return False

            instrument_id = instrument.get('tradableInstrumentId')

            # Get current positions
            positions = await self.accounts_client.get_current_position_async(
                account['id'],
                account['accNum']
            )

            if not positions or 'd' not in positions or 'positions' not in positions['d']:
                return False

            # Check if any position has this instrument ID
            for position in positions['d']['positions']:
                if str(position[1]) == str(instrument_id):
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking open positions: {e}", exc_info=True)
            return False  # Assume no positions on error (safer)

    async def get_pending_orders(self, account, instrument_name):
        """
        Get any pending orders for the specified instrument.

        Args:
            account (dict): Account information
            instrument_name (str): Name of the instrument to check

        Returns:
            list: List of pending order IDs
        """
        try:
            # Get instrument ID first
            instrument = await self.instruments_client.get_instrument_by_name_async(
                account['id'],
                account['accNum'],
                instrument_name
            )

            if not instrument:
                logger.warning(f"Instrument {instrument_name} not found")
                return []

            instrument_id = instrument.get('tradableInstrumentId')

            # Get all orders
            orders_response = await self.orders_client.get_orders_async(
                account['id'],
                account['accNum']
            )

            if not orders_response or 'd' not in orders_response or 'orders' not in orders_response['d']:
                return []

            pending_orders = []

            # Filter for pending orders with this instrument ID
            for order in orders_response['d']['orders']:
                # Check if order matches our instrument and is pending (not fully filled)
                if (str(order[1]) == str(instrument_id) and
                        order[6] in ['New', 'PartiallyFilled', 'Accepted', 'Working']):
                    pending_orders.append(order[0])  # order ID

            return pending_orders

        except Exception as e:
            logger.error(f"Error getting pending orders: {e}", exc_info=True)
            return []  # Assume no orders on error

    async def cancel_pending_orders(self, account, order_ids):
        """
        Cancel specific pending orders matching the TradeLocker API specification.

        Args:
            account (dict): Account information
            order_ids (list): List of specific order IDs to cancel

        Returns:
            int: Number of successfully cancelled orders
        """
        if not order_ids:
            return 0

        success_count = 0

        for order_id in order_ids:
            try:
                # Get the necessary values
                acc_num = account['accNum']

                # Create a custom request directly using the correct API endpoint
                headers = {
                    "Authorization": f"Bearer {await self.auth.get_access_token_async()}",
                    "accNum": str(acc_num)
                }

                url = f"{self.auth.base_url}/trade/orders/{order_id}"

                # Make the request directly instead of using the orders_client
                async with aiohttp.ClientSession() as session:
                    async with session.delete(url, headers=headers) as response:
                        if response.status == 200:
                            success_count += 1
                            logger.info(f"Successfully cancelled order {order_id}")
                        elif response.status == 404:
                            logger.info(f"Order {order_id} not found - may have already been filled or cancelled")
                        else:
                            logger.warning(f"Failed to cancel order {order_id} - status {response.status}")

            except Exception as e:
                logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)

        return success_count

    async def handle_message(self, message, account, colored_time, message_id=None,
                             channel_id=None, channel_name=None, reply_to_msg_id=None):
        """
        Main handler for processing incoming messages.

        Args:
            message (str): The message text
            account (dict): Account information
            colored_time (str): Formatted time string for logging
            message_id (str): Optional Telegram message ID
            channel_id (int/str): Optional ID of the channel source
            channel_name (str): Optional name of the channel source
            reply_to_msg_id (str): Optional ID of the message this is replying to

        Returns:
            tuple: (is_handled, result_info)
        """

        # Check if it's a TP hit message
        is_tp_hit, instrument, tp_level, tp_price, signal_hint = self.is_tp_hit_message(message, message_id)

        logger.info(
            f"DEBUG: TP hit detection result: is_hit={is_tp_hit}, instrument={instrument}, level={tp_level}"
        )

        # Handle TP hit message that's a reply (special case for your signal provider)
        if is_tp_hit and reply_to_msg_id:
            logger.info(f"Found a potential TP hit as a reply to message {reply_to_msg_id}")

            # Try to find the original signal by message ID
            original_signal = None
            original_instrument = None

            # Search through all instruments and signals
            for instr, signals in self.signal_history.items():
                for signal in signals:
                    if signal.get('signal_id') == reply_to_msg_id:
                        original_signal = signal
                        original_instrument = instr
                        break
                if original_signal:
                    break

            if original_signal:
                # We found the signal this TP hit is replying to!
                if not instrument:  # If we didn't detect instrument from the TP hit message itself
                    instrument = original_instrument

                signal_id = original_signal.get('signal_id')
                matching_orders = original_signal.get('related_orders', [])

                logger.info(f"Found matching signal for reply - instrument: {instrument}, signal_id: {signal_id}")

                # Check for open positions
                has_positions = await self.has_open_positions(account, instrument)

                if has_positions:
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}Found existing positions for {instrument}, no action needed{Style.RESET_ALL}"
                    )
                    return True, {"action": "none", "reason": "existing_positions"}

                # We have no positions, check if we need to cancel orders
                if matching_orders:
                    pending_orders = await self.get_pending_orders(account, instrument)
                    orders_to_cancel = [order_id for order_id in pending_orders if order_id in matching_orders]

                    if orders_to_cancel:
                        logger.warning(
                            f"{colored_time}: {Fore.RED}Found missed signal match for {instrument} - "
                            f"TP{tp_level} hit but no open positions. "
                            f"Cancelling {len(orders_to_cancel)} matched pending orders{Style.RESET_ALL}"
                        )

                        cancelled_count = await self.cancel_pending_orders(account, orders_to_cancel)

                        return True, {
                            "action": "cancelled",
                            "instrument": instrument,
                            "tp_level": tp_level,
                            "matched_signal_id": signal_id,
                            "total_orders": len(orders_to_cancel),
                            "cancelled_count": cancelled_count
                        }

                # No matching orders found
                logger.info(f"{colored_time}: Found signal match but no pending orders to cancel")
                return True, {"action": "none", "reason": "no_matching_orders"}

        # If not a valid TP hit message or couldn't match to a reply, return early
        if not is_tp_hit or not instrument:
            return False, None

        logger.info(
            f"{colored_time}: {Fore.YELLOW}Detected TP{tp_level} hit message for {instrument}{Style.RESET_ALL}" +
            (f" at price {tp_price}" if tp_price else "") +
            (f" from channel {channel_name}" if channel_name else "")
        )

        # Check for open positions
        has_positions = await self.has_open_positions(account, instrument)

        if has_positions:
            logger.info(
                f"{colored_time}: {Fore.GREEN}Found existing positions for {instrument}, no action needed{Style.RESET_ALL}"
            )
            return True, {"action": "none", "reason": "existing_positions"}

        # No positions found, check for matching signals from the same source
        matching_signal, signal_id, matching_orders = self.find_matching_signal(
            instrument, tp_level, tp_price, signal_hint
        )

        # Filter matching_signal to ensure it's from the same source and is recent
        if matching_signal:
            signal_matches_source = self.is_signal_from_same_source(matching_signal, channel_id)
            signal_is_recent = self.is_signal_recent(matching_signal)

            if not signal_matches_source:
                logger.info(
                    f"{colored_time}: Found potential signal match but from different source. "
                    f"TP hit from channel {channel_id}, signal from channel {matching_signal.get('channel_id')}"
                )
                matching_signal = None
                signal_id = None
                matching_orders = []

            if not signal_is_recent:
                logger.info(
                    f"{colored_time}: Found potential signal match but it's too old. "
                    f"Signal timestamp: {matching_signal.get('timestamp')}"
                )
                matching_signal = None
                signal_id = None
                matching_orders = []

        # Get all pending orders for this instrument, regardless of signal matching
        pending_orders = await self.get_pending_orders(account, instrument)

        # Determine which orders to cancel based on matches
        orders_to_cancel = []

        if matching_orders and pending_orders:
            # Cancel only orders associated with the matched signal
            orders_to_cancel = [
                order_id for order_id in pending_orders
                if order_id in matching_orders
            ]

            if orders_to_cancel:
                logger.warning(
                    f"{colored_time}: {Fore.RED}Found missed signal match for {instrument} - "
                    f"TP{tp_level} hit but no open positions. "
                    f"Cancelling {len(orders_to_cancel)} matched pending orders{Style.RESET_ALL}"
                )
            else:
                # We found a matching signal but no matching pending orders
                logger.info(
                    f"{colored_time}: {Fore.YELLOW}Found signal match for {instrument} "
                    f"but no matching pending orders to cancel{Style.RESET_ALL}"
                )
        elif pending_orders and self.enable_fallback_protection:
            # No specific signal match, but we have pending orders - cancel if fallback enabled
            orders_to_cancel = pending_orders
            logger.warning(
                f"{colored_time}: {Fore.RED}No specific signal match for {instrument} TP{tp_level} hit, "
                f"but found {len(orders_to_cancel)} pending orders with no positions. "
                f"Fallback protection is ENABLED - cancelling all pending orders.{Style.RESET_ALL}"
            )
        elif pending_orders:
            # No specific signal match, have pending orders, but fallback protection disabled
            logger.warning(
                f"{colored_time}: {Fore.YELLOW}No specific signal match for {instrument} TP{tp_level} hit. "
                f"Found {len(pending_orders)} pending orders but Fallback Protection is DISABLED. "
                f"Not cancelling orders. To enable set enable_fallback_protection=True{Style.RESET_ALL}"
            )
            return True, {"action": "none", "reason": "fallback_protection_disabled"}
        else:
            # No pending orders found
            logger.info(
                f"{colored_time}: {Fore.YELLOW}No pending orders found for {instrument}{Style.RESET_ALL}"
            )
            return True, {"action": "none", "reason": "no_pending_orders"}

        # Cancel the identified orders

        cancelled_count = await self.cancel_pending_orders(account, orders_to_cancel)

        result = {
            "action": "cancelled",
            "instrument": instrument,
            "tp_level": tp_level,
            "matched_signal_id": signal_id,
            "total_orders": len(orders_to_cancel),
            "cancelled_count": cancelled_count,
            "fallback_used": bool(not matching_signal and self.enable_fallback_protection)
        }

        return True, result