import re
import logging
import asyncio
from datetime import datetime
from colorama import Fore, Style

logger = logging.getLogger(__name__)


class SignalManagementHandler:
    """
    Handles signal management instructions like "move to breakeven" or "close early"
    from signal provider replies.
    """

    def __init__(self, accounts_client, orders_client, instruments_client, quotes_client, auth_client):
        self.accounts_client = accounts_client
        self.orders_client = orders_client
        self.instruments_client = instruments_client
        self.quotes_client = quotes_client
        self.auth = auth_client
        self.signal_history = {}  # Reference to missed signal handler's history

        # Configuration options that can be modified based on risk profile
        self.auto_breakeven = True  # Whether to automatically move SL to breakeven
        self.auto_close_early = True  # Whether to automatically close positions when recommended
        self.confirmation_required = False  # Whether to ask for confirmation before actions
        self.partial_closure_percent = 50  # Percentage to close when partial closure is recommended

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
            r"take\s+(?:your\s+)?profits?"
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
        # Check for common forex pairs and instruments
        instrument_patterns = [
            r'\b(EUR/?USD)\b',
            r'\b(GBP/?USD)\b',
            r'\b(USD/?JPY)\b',
            r'\b(USD/?CAD)\b',
            r'\b(AUD/?USD)\b',
            r'\b(NZD/?USD)\b',
            r'\b(USD/?CHF)\b',
            r'\b(XAUUSD|GOLD)\b',
            r'\b(DJI30|US30)\b',
            r'\b(NDX100|NAS100)\b'
        ]

        for pattern in instrument_patterns:
            match = re.search(pattern, message.upper())
            if match:
                instr = match.group(1).replace('/', '')

                # Normalize instrument names
                if instr == 'GOLD':
                    instr = 'XAUUSD'
                elif instr == 'US30':
                    instr = 'DJI30'
                elif instr == 'NAS100':
                    instr = 'NDX100'

                return instr

        return None

    async def find_matching_positions(self, account, instrument=None):
        """Find currently open positions matching the instrument"""
        try:
            positions = await self.accounts_client.get_current_position_async(
                account['id'],
                account['accNum']
            )

            if not positions or 'd' not in positions or 'positions' not in positions['d']:
                return []

            open_positions = []

            for position in positions['d']['positions']:
                position_id = position[0]
                instrument_id = position[1]

                # If no specific instrument requested, add all positions
                if not instrument:
                    open_positions.append({
                        'position_id': position_id,
                        'instrument_id': instrument_id,
                        'side': position[3],
                        'quantity': position[4],
                        'entry_price': position[5]
                    })
                    continue

                # If instrument specified, look up the instrument to match
                position_instrument = await self.instruments_client.get_instrument_by_id_async(
                    account['id'],
                    account['accNum'],
                    instrument_id
                )

                if position_instrument and position_instrument.get('name') == instrument:
                    open_positions.append({
                        'position_id': position_id,
                        'instrument_id': instrument_id,
                        'instrument_name': instrument,
                        'side': position[3],
                        'quantity': position[4],
                        'entry_price': position[5]
                    })

            return open_positions

        except Exception as e:
            logger.error(f"Error finding matching positions: {e}")
            return []

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

            # Update the stop loss
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

    async def handle_management_instruction(self, account, instruction_type, instrument, details, colored_time):
        """
        Execute the management instruction based on its type

        Args:
            account: Account information
            instruction_type: Type of instruction ('breakeven', 'close', 'partial_close')
            instrument: Instrument name or None for all positions
            details: Additional details for the instruction
            colored_time: Formatted time for logging

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

        # Find matching positions
        positions = await self.find_matching_positions(account, instrument)

        if not positions:
            logger.info(
                f"{colored_time}: No matching positions found for {instrument if instrument else 'any instrument'}")
            return False

        # For confirmation if required
        if self.confirmation_required:
            if instruction_type == 'breakeven':
                confirmation = input(
                    f"{Fore.YELLOW}Move stop loss to breakeven for {len(positions)} positions? (y/n): {Style.RESET_ALL}")
                if confirmation.lower() != 'y':
                    logger.info(f"{colored_time}: Breakeven operation cancelled by user")
                    return False

            elif instruction_type == 'close':
                confirmation = input(f"{Fore.RED}Close {len(positions)} positions completely? (y/n): {Style.RESET_ALL}")
                if confirmation.lower() != 'y':
                    logger.info(f"{colored_time}: Close operation cancelled by user")
                    return False

            elif instruction_type == 'partial_close':
                percentage = details.get('percentage', self.partial_closure_percent)
                confirmation = input(
                    f"{Fore.YELLOW}Close {percentage}% of {len(positions)} positions? (y/n): {Style.RESET_ALL}")
                if confirmation.lower() != 'y':
                    logger.info(f"{colored_time}: Partial close operation cancelled by user")
                    return False

        # Execute the appropriate action for each position
        success_count = 0

        for position in positions:
            if instruction_type == 'breakeven':
                result = await self.modify_position_sl_to_breakeven(account, position)
                if result:
                    success_count += 1
                    logger.info(
                        f"{colored_time}: {Fore.GREEN}Moved SL to breakeven for position {position['position_id']}{Style.RESET_ALL}")

            elif instruction_type == 'close':
                result = await self.close_position(account, position)
                if result:
                    success_count += 1
                    logger.info(f"{colored_time}: {Fore.RED}Closed position {position['position_id']}{Style.RESET_ALL}")

            elif instruction_type == 'partial_close':
                percentage = details.get('percentage', self.partial_closure_percent)
                result = await self.close_position(account, position, percentage)
                if result:
                    success_count += 1
                    logger.info(
                        f"{colored_time}: {Fore.YELLOW}Closed {percentage}% of position {position['position_id']}{Style.RESET_ALL}")

        # Return overall success
        if success_count > 0:
            logger.info(f"{colored_time}: Successfully managed {success_count} out of {len(positions)} positions")
            return True
        else:
            logger.warning(f"{colored_time}: Failed to manage any positions")
            return False

    async def handle_message(self, message, account, colored_time, reply_to_msg_id=None):
        """
        Main handler for processing management messages from signal providers

        Args:
            message: Message text
            account: Account information
            colored_time: Formatted time for logging
            reply_to_msg_id: ID of message this is replying to (if any)

        Returns:
            tuple: (is_handled, result_info)
        """
        # Check if this is a management instruction
        instruction_type, instrument, details = self.is_management_instruction(message, reply_to_msg_id)

        if not instruction_type:
            return False, None

        # Log the detected instruction
        instruction_color = Fore.CYAN if instruction_type == 'breakeven' else (
            Fore.RED if instruction_type == 'close' else Fore.YELLOW)
        logger.info(f"{colored_time}: {instruction_color}Detected {instruction_type} instruction{Style.RESET_ALL}" +
                    (f" for {instrument}" if instrument else ""))

        # If no specific instrument was detected but this is a reply to a known signal
        if not instrument and reply_to_msg_id:
            # Try to find the original signal from the reply_to_msg_id
            original_instrument = None

            # Search through signal history to find matching message ID
            for instr, signals in self.signal_history.items():
                for signal in signals:
                    if signal.get('signal_id') == reply_to_msg_id:
                        original_instrument = instr
                        break
                if original_instrument:
                    break

            if original_instrument:
                instrument = original_instrument
                logger.info(f"{colored_time}: {Fore.GREEN}Matched reply to signal for {instrument}{Style.RESET_ALL}")

        # Execute the instruction
        result = await self.handle_management_instruction(
            account, instruction_type, instrument, details, colored_time
        )

        return True, {
            "instruction_type": instruction_type,
            "instrument": instrument,
            "details": details,
            "success": result
        }