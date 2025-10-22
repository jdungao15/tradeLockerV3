import requests
import aiohttp
import json
import os
import logging
import asyncio
import re
from dotenv import load_dotenv
from utils.instrument_utils import normalize_instrument_name

load_dotenv()
logger = logging.getLogger(__name__)

api_key = os.getenv("OPENAI_API_KEY")
api_url = "https://api.openai.com/v1/chat/completions"

# Cache for parsed signals to avoid duplicate processing
parsed_signal_cache = {}

# Broker price difference configuration
# This can be adjusted based on observed differences between signal provider and your broker
BROKER_PRICE_ADJUSTMENTS = {
    "DJI30": 0,  # Adjustment from signal provider to your broker (42764 -> 42760)
    "NDX100": 0,  # Add adjustment 1s for other CFDs as needed
    "XAUUSD": 0  # Add adjustments for other instruments as needed
}


def is_potential_trading_signal(message: str) -> bool:
    """
    Pre-filter to determine if a message might be a trading signal
    before sending to OpenAI API.
    """
    # Normalize message for analysis
    message_lower = message.lower()

    # Check for specific trading terms like buy, sell, entry, etc.
    trading_terms = ['buy', 'sell', 'entry', 'stop', 'sl', 'tp', 'target', 'take profit', 'long', 'short']
    has_trading_terms = any(term in message_lower for term in trading_terms)

    # Check for trading instruments
    # Common instruments list
    instruments = [
        'xauusd',
        'gold',
        'eurusd',
        'gbpusd',
        'usdjpy',
        'us30',
        'dji30',
        'nas100',
        'ndx100',
        'silver',
        'xagusd']
    has_instrument = any(instrument in message_lower for instrument in instruments)

    # Also check for forex pair patterns (e.g., USDCAD, EURJPY, GBPCAD, etc.)
    # Forex pairs are typically 6 letters: 3 letters + 3 letters (e.g., USDCAD)
    if not has_instrument:
        forex_pattern = r'\b[A-Z]{3}[A-Z]{3}\b'
        has_instrument = bool(re.search(forex_pattern, message.upper()))

    # Check for price patterns (numbers that might be price points)
    has_prices = bool(re.search(r'\d+\.\d+|\d+', message))

    # Check for excess emojis (often in announcement messages, not signals)
    emoji_count = len(re.findall(r'[\U00010000-\U0010ffff]|[\u2600-\u26FF\u2700-\u27BF]', message))
    too_many_emojis = emoji_count > 10  # Adjust threshold as needed

    # Check message length (real signals are typically longer than a few words)
    too_short = len(message.split()) < 3

    # Special case: Check for "PIPS" announcements (often not actionable signals)
    is_pips_announcement = 'pips' in message_lower and any(x in message_lower for x in ['hit', 'reached', 'secured'])

    # Return True if it looks like a signal, False otherwise
    return (has_trading_terms and has_instrument and has_prices and
            not too_many_emojis and not too_short and not is_pips_announcement)


def adjust_broker_pricing(parsed_signal):
    """
    Adjust prices in parsed signal to match broker pricing.

    For indices and other CFDs, applies configured price adjustments to account for
    differences between signal provider and broker pricing.
    """
    if not parsed_signal:
        return parsed_signal

    instrument = parsed_signal.get('instrument')

    # Check if we have a configured adjustment for this instrument
    if instrument in BROKER_PRICE_ADJUSTMENTS:
        adjustment = BROKER_PRICE_ADJUSTMENTS[instrument]

        if adjustment == 0:
            return parsed_signal  # No adjustment needed

        logger.info(f"Applying {adjustment} point adjustment to {instrument} signal")

        # Adjust entry point
        if 'entry_point' in parsed_signal:
            parsed_signal['entry_point'] += adjustment
            logger.info(f"Adjusted entry point: {parsed_signal['entry_point']}")

        # Adjust stop loss
        if 'stop_loss' in parsed_signal:
            parsed_signal['stop_loss'] += adjustment
            logger.info(f"Adjusted stop loss: {parsed_signal['stop_loss']}")

        # Adjust take profits
        if 'take_profits' in parsed_signal and parsed_signal['take_profits']:
            parsed_signal['take_profits'] = [tp + adjustment for tp in parsed_signal['take_profits']]
            logger.info(f"Adjusted take profits: {parsed_signal['take_profits']}")

    # Special adjustments for specific instruments (kept from original function)
    if instrument == 'DJI30':
        # Get order direction for potential direction-based adjustments
        # Handle order types with modifiers (e.g., 'buy limit', 'sell stop')
        is_buy = 'buy' in parsed_signal.get('order_type', '').lower()

        # Apply additional 5-pip adjustment for broker spread differences
        # This is in addition to the absolute price level adjustment above
        direction_adjustment = 5 if is_buy else -5

        # Only adjust take profits for this directional adjustment
        if 'take_profits' in parsed_signal and parsed_signal['take_profits']:
            parsed_signal['take_profits'] = [tp + direction_adjustment for tp in parsed_signal['take_profits']]
            logger.info(
                f"Applied additional directional adjustment of {direction_adjustment} to take profits: {parsed_signal['take_profits']}")

    return parsed_signal


def parse_signal(message: str):
    """
    Parse a trading signal using OpenAI API - synchronous version.
    Caches results to avoid re-parsing identical messages.
    """
    # Check cache first
    if message in parsed_signal_cache:
        logger.debug("Using cached parsed signal")
        return parsed_signal_cache[message]

    # Pre-filter to avoid unnecessary API calls
    if not is_potential_trading_signal(message):
        logger.info("Message doesn't appear to be a valid trading signal, skipping API call")
        parsed_signal_cache[message] = None  # Cache the negative result
        return None

    # Debug: Log the raw message being parsed
    logger.debug(f"Parsing new signal from Telegram: {message[:150]}...")

    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"},
            json={
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a trading signal parser. Always respond with a valid JSON object and nothing else."},
                    {
                        "role": "user",
                        "content": f'''Parse the following trading signal and return a JSON object:

                        "{message}"

                        Rules:
                        1. The JSON object should have these fields: instrument, order_type, entry_point, stop_loss, and take_profits.
                        1.1 orderType MUST preserve the full order type from the message:
                            - If the message contains "LIMIT" or "BUY LIMIT" or "SELL LIMIT", use "buy limit" or "sell limit"
                            - If the message contains "STOP" or "BUY STOP" or "SELL STOP", use "buy stop" or "sell stop"
                            - If the message contains "MARKET", use "buy market" or "sell market"
                            - Otherwise, just use "buy" or "sell"
                            - IMPORTANT: Always check the original message for these keywords and include them in the order_type
                        2. If the entry point is a range, use the first value.
                        3. If the stop loss is a range, use the first value.
                        4. take_profits should always be an array, even if there's only one value.
                        4.1 Only takes the first 3 take profits.
                        4.2 if its index like DJI30, US30 NDX100 or NAS100 take all profits
                        5. Convert instrument names as follows:
                           - US30 to DJI30
                           - NAS100 to NDX100
                           - GOLD to XAUUSD
                           - SILVER to XAGUSD
                        6. Ensure all numeric values are numbers, not strings.
                        7. Make sure that the fields are in the correct format and order and cannot be null or empty.
                        8. If the input is not a valid trading signal, return null.
                        9.Naming convention should be snake case like in python.


                        Respond only with the JSON object or null, no additional text.'''}]})
        content = response.json()["choices"][0]["message"]["content"].strip()
        logger.debug(f"Content from signal_parser.py: {content}")

        if content.lower() == "null":
            logger.info("Not a valid trading signal")
            parsed_signal_cache[message] = None
            return None

        try:
            result = json.loads(content)

            # Debug: Log what was parsed
            logger.debug(f"OpenAI parsed order_type as: '{result.get('order_type', 'MISSING')}'")

            # Validate that required fields are present
            required_fields = ['instrument', 'order_type', 'entry_point', 'stop_loss', 'take_profits']
            if not all(field in result for field in required_fields):
                logger.warning(f"Parsed signal is missing required fields: {result}")
                parsed_signal_cache[message] = None
                return None

            # POST-PROCESSING: Fix order_type if OpenAI missed LIMIT/STOP/MARKET
            order_type = result.get('order_type', '').lower()
            message_upper = message.upper()

            # Check if the original message contains order type modifiers that OpenAI missed
            if 'limit' not in order_type and 'LIMIT' in message_upper:
                if 'buy' in order_type:
                    result['order_type'] = 'buy limit'
                    logger.debug("Corrected order_type to 'buy limit' (OpenAI missed it)")
                elif 'sell' in order_type:
                    result['order_type'] = 'sell limit'
                    logger.debug("Corrected order_type to 'sell limit' (OpenAI missed it)")

            elif 'stop' not in order_type and 'STOP' in message_upper:
                if 'buy' in order_type:
                    result['order_type'] = 'buy stop'
                    logger.debug("Corrected order_type to 'buy stop' (OpenAI missed it)")
                elif 'sell' in order_type:
                    result['order_type'] = 'sell stop'
                    logger.debug("Corrected order_type to 'sell stop' (OpenAI missed it)")

            elif 'market' not in order_type and 'MARKET' in message_upper:
                if 'buy' in order_type:
                    result['order_type'] = 'buy market'
                    logger.debug("Corrected order_type to 'buy market' (OpenAI missed it)")
                elif 'sell' in order_type:
                    result['order_type'] = 'sell market'
                    logger.debug("Corrected order_type to 'sell market' (OpenAI missed it)")

            logger.debug(f"Final order_type after post-processing: '{result['order_type']}'")

            # Ensure take_profits is a list
            if not isinstance(result.get('take_profits', []), list):
                logger.warning("take_profits is not a list, converting to list")
                result['take_profits'] = [result['take_profits']]

            # Ensure numeric values are actually numbers
            for field in ['entry_point', 'stop_loss']:
                if not isinstance(result.get(field), (int, float)):
                    logger.warning(f"Field {field} is not numeric: {result.get(field)}")
                    parsed_signal_cache[message] = None
                    return None

            # Ensure take_profits contains numeric values
            if not all(isinstance(tp, (int, float)) for tp in result.get('take_profits', [])):
                logger.warning(f"take_profits contains non-numeric values: {result.get('take_profits')}")
                parsed_signal_cache[message] = None
                return None

            # Ensure order_type is valid (allow buy, sell, and their modifiers)
            valid_order_types = [
                'buy',
                'sell',
                'buy limit',
                'sell limit',
                'buy stop',
                'sell stop',
                'buy market',
                'sell market']
            if result.get('order_type') not in valid_order_types:
                logger.warning(f"Invalid order_type: {result.get('order_type')}")
                parsed_signal_cache[message] = None
                return None

            # Normalize instrument name
            if 'instrument' in result:
                canonical_name = normalize_instrument_name(result['instrument'])
                logger.debug(f"Normalized instrument name from {result['instrument']} to {canonical_name}")
                result['instrument'] = canonical_name

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing OpenAI response: {e}")
            parsed_signal_cache[message] = None
            return None

        # Apply broker price adjustments
        result = adjust_broker_pricing(result)

        # Cache the result
        parsed_signal_cache[message] = result
        return result

    except Exception as e:
        logger.error(f"Error parsing signal: {e}", exc_info=True)
        parsed_signal_cache[message] = None
        return None


def is_reduced_risk_signal(message: str) -> bool:
    """
    Check if the signal suggests reduced risk (high risk, small size, small lot).

    Args:
        message: The signal message text

    Returns:
        bool: True if the signal suggests using reduced risk, False otherwise
    """
    message_lower = message.lower()
    risk_keywords = ['high risk', 'small size', 'small lot', 'risky', 'conservative entry',
                     'small position', 'reduced size', 'lower size', 'careful']
    return any(keyword in message_lower for keyword in risk_keywords)


async def parse_signal_async(message: str):
    """
    Parse a trading signal using OpenAI API - asynchronous version.
    Caches results to avoid re-parsing identical messages.
    """
    # Check cache first
    if message in parsed_signal_cache:
        logger.info("Using cached parsed signal")
        return parsed_signal_cache[message]

    # Pre-filter to avoid unnecessary API calls
    if not is_potential_trading_signal(message):
        logger.info("Message doesn't appear to be a valid trading signal, skipping API call")
        parsed_signal_cache[message] = None  # Cache the negative result
        return None

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {"model": "gpt-4",
                   "messages": [{"role": "system",
                                 "content": "You are a trading signal parser. Always respond with a valid JSON object and nothing else."},
                                {"role": "user",
                                 "content": f'''Parse the following trading signal and return a JSON object:

                    "{message}"

                    Rules:
                    1. The JSON object should have these fields: instrument, order_type, entry_point, stop_loss, and take_profits.
                    1.1 orderType MUST preserve the full order type from the message:
                        - If the message contains "LIMIT" or "BUY LIMIT" or "SELL LIMIT", use "buy limit" or "sell limit"
                        - If the message contains "STOP" or "BUY STOP" or "SELL STOP", use "buy stop" or "sell stop"
                        - If the message contains "MARKET", use "buy market" or "sell market"
                        - Otherwise, just use "buy" or "sell"
                        - IMPORTANT: Always check the original message for these keywords and include them in the order_type
                    2. If the entry point is a range, use the first value.
                    3. If the stop loss is a range, use the first value.
                    4. take_profits should always be an array, even if there's only one value.
                    4.1 Only takes the first 3 take profits.
                    4.2 if its index like DJI30, US30 NDX100 or NAS100 take all profits
                    5. Convert instrument names as follows:
                       - US30 to DJI30
                       - NAS100 to NDX100
                       - GOLD to XAUUSD
                       - SILVER to XAGUSD
                    6. Ensure all numeric values are numbers, not strings.
                    7. Make sure that the fields are in the correct format and order and cannot be null or empty.
                    8. If the input is not a valid trading signal, return null.
                    9.Naming convention should be snake case like in python.


                    Respond only with the JSON object or null, no additional text.'''}]}

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                response.raise_for_status()
                json_response = await response.json()
                content = json_response["choices"][0]["message"]["content"].strip()

                logger.debug(f"Content from signal_parser.py: {content}")

                if content.lower() == "null":
                    logger.info("Not a valid trading signal")
                    parsed_signal_cache[message] = None
                    return None

                try:
                    result = json.loads(content)

                    # Validate that required fields are present
                    required_fields = ['instrument', 'order_type', 'entry_point', 'stop_loss', 'take_profits']
                    if not all(field in result for field in required_fields):
                        logger.warning(f"Parsed signal is missing required fields: {result}")
                        parsed_signal_cache[message] = None
                        return None

                    # POST-PROCESSING: Fix order_type if OpenAI missed LIMIT/STOP/MARKET
                    order_type = result.get('order_type', '').lower()
                    message_upper = message.upper()

                    # Check if the original message contains order type modifiers that OpenAI missed
                    if 'limit' not in order_type and 'LIMIT' in message_upper:
                        if 'buy' in order_type:
                            result['order_type'] = 'buy limit'
                            logger.debug("Corrected order_type to 'buy limit' (OpenAI missed it)")
                        elif 'sell' in order_type:
                            result['order_type'] = 'sell limit'
                            logger.debug("Corrected order_type to 'sell limit' (OpenAI missed it)")

                    elif 'stop' not in order_type and 'STOP' in message_upper:
                        if 'buy' in order_type:
                            result['order_type'] = 'buy stop'
                            logger.debug("Corrected order_type to 'buy stop' (OpenAI missed it)")
                        elif 'sell' in order_type:
                            result['order_type'] = 'sell stop'
                            logger.debug("Corrected order_type to 'sell stop' (OpenAI missed it)")

                    elif 'market' not in order_type and 'MARKET' in message_upper:
                        if 'buy' in order_type:
                            result['order_type'] = 'buy market'
                            logger.debug("Corrected order_type to 'buy market' (OpenAI missed it)")
                        elif 'sell' in order_type:
                            result['order_type'] = 'sell market'
                            logger.debug("Corrected order_type to 'sell market' (OpenAI missed it)")

                    logger.debug(f"Final order_type after post-processing: '{result['order_type']}'")

                    # Ensure take_profits is a list
                    if not isinstance(result.get('take_profits', []), list):
                        logger.warning("take_profits is not a list, converting to list")
                        result['take_profits'] = [result['take_profits']]

                    # Ensure numeric values are actually numbers
                    for field in ['entry_point', 'stop_loss']:
                        if not isinstance(result.get(field), (int, float)):
                            logger.warning(f"Field {field} is not numeric: {result.get(field)}")
                            parsed_signal_cache[message] = None
                            return None

                    # Ensure take_profits contains numeric values
                    if not all(isinstance(tp, (int, float)) for tp in result.get('take_profits', [])):
                        logger.warning(f"take_profits contains non-numeric values: {result.get('take_profits')}")
                        parsed_signal_cache[message] = None
                        return None

                    # Ensure order_type is valid (allow buy, sell, and their modifiers)
                    valid_order_types = [
                        'buy',
                        'sell',
                        'buy limit',
                        'sell limit',
                        'buy stop',
                        'sell stop',
                        'buy market',
                        'sell market']
                    if result.get('order_type') not in valid_order_types:
                        logger.warning(f"Invalid order_type: {result.get('order_type')}")
                        parsed_signal_cache[message] = None
                        return None

                    # Check if this is a reduced risk signal and add the flag
                    result['reduced_risk'] = is_reduced_risk_signal(message)
                    if result['reduced_risk']:
                        logger.info(f"Signal identified as reduced risk: {message[:100]}...")

                    # Normalize instrument name to canonical form
                    if 'instrument' in result:
                        canonical_name = normalize_instrument_name(result['instrument'])
                        logger.debug(f"Normalized instrument name from {result['instrument']} to {canonical_name}")
                        result['instrument'] = canonical_name

                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing OpenAI response: {e}")
                    parsed_signal_cache[message] = None
                    return None

                # Apply broker price adjustments
                result = adjust_broker_pricing(result)

                # Cache the result
                parsed_signal_cache[message] = result
                return result

    except Exception as e:
        logger.error(f"Error parsing signal: {e}", exc_info=True)
        parsed_signal_cache[message] = None
        return None


async def find_matching_instrument(instruments_client, account, parsed_signal):
    """
    Find the matching instrument in the platform for the signal using
    a bidirectional matching system for maximum flexibility across brokers.

    Args:
        instruments_client: TradeLocker instruments client
        account: Account information dictionary
        parsed_signal: Parsed signal with normalized instrument name

    Returns:
        dict: Instrument data from the platform or None if not found
    """
    from utils.instrument_utils import (
        get_available_instruments,
        identify_instrument_group,
        score_instrument_match
    )

    canonical_name = parsed_signal['instrument']
    logger.debug(f"Looking for instrument: {canonical_name}")

    # Get all available instruments first to avoid multiple API calls
    available_instruments = await get_available_instruments(instruments_client, account)
    if not available_instruments:
        logger.warning("❌ Failed to retrieve available instruments")
        return None

    # Display all available instruments to help with debugging
    instrument_names = [i.get('name', '') for i in available_instruments]
    logger.debug(f"Available instruments: {instrument_names}")

    # Identify which instrument group the signal belongs to
    group_name, target_nicknames = identify_instrument_group(canonical_name)

    if group_name:
        logger.debug(f"Signal instrument '{canonical_name}' identified as '{group_name}'")
        logger.debug(f"Will try these nicknames for matching: {target_nicknames}")
    else:
        logger.debug(f"Could not identify a known instrument group for '{canonical_name}'")
        # In this case, target_nicknames will just contain the original name

    # Score and sort all available instruments
    scored_instruments = []
    for instrument in available_instruments:
        instr_name = instrument.get('name', '')
        score = score_instrument_match(instr_name, target_nicknames)
        if score > 0:
            scored_instruments.append((score, instr_name, instrument))

    # Sort by score descending
    scored_instruments.sort(reverse=True)

    # Try each potential match in order of score
    for score, instr_name, _ in scored_instruments:
        logger.debug(f"Trying potential match: {instr_name} (score: {score})")

        instrument_data = await instruments_client.get_instrument_by_name_async(
            account['id'],
            account['accNum'],
            instr_name
        )

        if instrument_data:
            logger.debug(f"Successfully matched {canonical_name} to broker instrument: {instr_name}")
            return instrument_data

    # If no matches were found via nickname matching, try the fallback approaches

    # 1. Try exact canonical name (might have been skipped if not in any group)
    instrument_data = await instruments_client.get_instrument_by_name_async(
        account['id'],
        account['accNum'],
        canonical_name
    )

    if instrument_data:
        logger.info(f"Found exact match for instrument {canonical_name}")
        return instrument_data

    # 2. Try common suffixes
    for suffix in ['.C', '.X', '.Z', '+', '-', '_']:
        test_name = f"{canonical_name}{suffix}"

        instrument_data = await instruments_client.get_instrument_by_name_async(
            account['id'],
            account['accNum'],
            test_name
        )

        if instrument_data:
            logger.info(f"Found match by adding suffix: {test_name}")
            return instrument_data

    # 3. Try without suffix if the original name has one
    if any(char in canonical_name for char in ['.', '+', '-', '_']):
        # Extract base name by removing any suffix
        base_name = re.sub(r'[.+\-_].*$', '', canonical_name)

        instrument_data = await instruments_client.get_instrument_by_name_async(
            account['id'],
            account['accNum'],
            base_name
        )

        if instrument_data:
            logger.info(f"Found match by removing suffix: {base_name}")
            return instrument_data

    # 4. Last resort - loop through all instruments and do a manual substring check
    # This handles cases where the instrument name is completely different but might contain
    # some identifying part
    for instrument in available_instruments:
        instr_name = instrument.get('name', '').upper()
        base_canonical = canonical_name.upper()

        # Clean up both names for comparison (remove special chars)
        clean_instr = re.sub(r'[^A-Z0-9]', '', instr_name)
        clean_canonical = re.sub(r'[^A-Z0-9]', '', base_canonical)

        # Check for substantial overlap
        if (clean_canonical in clean_instr or
                clean_instr in clean_canonical or
                any(part for part in clean_canonical.split() if len(part) > 2 and part in clean_instr)):

            instrument_data = await instruments_client.get_instrument_by_name_async(
                account['id'],
                account['accNum'],
                instrument.get('name', '')
            )

            if instrument_data:
                logger.info(f"Found match using substring matching: {instrument.get('name', '')}")
                return instrument_data

    logger.warning(f"No matching instrument found for {canonical_name}")
    return None


# Helper function to extract price points from complex messages
def extract_price_points(text: str):
    """
    Extracts potential price points like entry points, stop loss levels,
    and take profit targets from text.
    Returns a dictionary of identified values.
    """
    import re

    # Patterns to match common price formats
    entry_patterns = [
        r"(?:entry|buy|sell)(?:\s+at)?\s+(?:around|near|at)?\s*:?\s*(\d+\.?\d*)",
        r"(?:entry|buy|sell)(?:\s+around|near)?\s*:?\s*(\d+\.?\d*)",
        r"(?:entry|buy|sell)(?:\s+point)?\s*:?\s*(\d+\.?\d*)"
    ]

    stop_patterns = [
        r"(?:stop|sl|stop\s+loss)(?:\s+at)?\s*:?\s*(\d+\.?\d*)",
        r"(?:stop|sl|stop\s+loss)(?:\s+around|near)?\s*:?\s*(\d+\.?\d*)"
    ]

    target_patterns = [
        r"(?:target|tp|take\s+profit|profit\s+target)\s*:?\s*(\d+\.?\d*)",
        r"(?:target|tp|take\s+profit|profit\s+target)\s+(\d+)\s*:?\s*(\d+\.?\d*)",
        r"(?:targets|tps|take\s+profits)\s*:?\s*(\d+\.?\d*)[,\s]+(\d+\.?\d*)[,\s]+(\d+\.?\d*)"
    ]

    results = {
        "potential_entries": [],
        "potential_stops": [],
        "potential_targets": []
    }

    # Extract entries
    for pattern in entry_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            results["potential_entries"].extend([float(m) for m in matches if m])

    # Extract stops
    for pattern in stop_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            results["potential_stops"].extend([float(m) for m in matches if m])

    # Extract targets - simple cases
    for pattern in target_patterns[:2]:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            for match in matches:
                if isinstance(match, tuple):
                    # Format with target number and value
                    results["potential_targets"].append(float(match[-1]))
                else:
                    # Simple value
                    results["potential_targets"].append(float(match))

    # Extract multiple targets in one line
    for pattern in target_patterns[2:]:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            for match in matches:
                # Add all values from the tuple
                results["potential_targets"].extend([float(m) for m in match if m])

    return results


# Function to update broker price adjustments based on observation
def update_broker_adjustment(instrument, provider_price, broker_price):
    """
    Update the broker price adjustment for a specific instrument based on observed prices.

    Args:
        instrument: The instrument code (e.g., 'DJI30')
        provider_price: The current price from the signal provider
        broker_price: The current price from your broker

    Returns:
        The calculated adjustment (broker_price - provider_price)
    """
    adjustment = broker_price - provider_price

    # Update the global adjustment configuration
    BROKER_PRICE_ADJUSTMENTS[instrument] = adjustment

    logger.info(f"Updated price adjustment for {instrument}: {adjustment} points")
    logger.info(f"Provider price: {provider_price}, Broker price: {broker_price}")

    return adjustment


def filter_take_profits_by_preference(take_profits, selection_config):
    """
    Filter take profits based on user preferences

    Args:
        take_profits: List of take profits from signal
        selection_config: Config dict from risk_config.get_tp_selection()

    Returns:
        list: Filtered take profits
    """
    mode = selection_config.get('mode', 'all')

    if mode == 'all' or not take_profits:
        return take_profits

    if mode == 'first_only':
        return take_profits[:1]

    if mode == 'first_two':
        return take_profits[:2]

    if mode == 'last_two':
        return take_profits[-2:] if len(take_profits) >= 2 else take_profits

    if mode == 'odd':
        return [tp for i, tp in enumerate(take_profits) if i % 2 == 0]  # 0-indexed, so even indices are odd TPs

    if mode == 'even':
        return [tp for i, tp in enumerate(take_profits) if i % 2 == 1]  # 0-indexed, so odd indices are even TPs

    if mode == 'custom':
        custom_indices = selection_config.get('custom_selection', [1, 2, 3, 4])
        # Convert 1-based indices to 0-based for list access
        indices_0_based = [i - 1 for i in custom_indices if 0 < i <= len(take_profits)]
        return [take_profits[i] for i in indices_0_based]

    return take_profits  # Default to all

# Clear signal cache periodically (every 24 hours)


async def cache_maintenance_task():
    """Background task to clear signal cache periodically"""
    while True:
        try:
            await asyncio.sleep(86400)  # 24 hours
            parsed_signal_cache.clear()
            logger.info("Signal parser cache cleared")
        except Exception as e:
            logger.error(f"Error in cache maintenance: {e}")
            await asyncio.sleep(3600)  # Try again in an hour if error occurs


# Start the cache maintenance task
def start_cache_maintenance():
    """Start the cache maintenance background task"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(cache_maintenance_task())
            logger.info("Signal parser cache maintenance task started")
    except RuntimeError:
        # No event loop, probably running in sync context
        pass


# Initialize cache maintenance
start_cache_maintenance()

# Initialize with current observed pricing difference for DJI30
update_broker_adjustment('DJI30', 42439, 42442)
