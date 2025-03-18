import requests
import aiohttp
import json
import os
import logging
import asyncio
import re
from dotenv import load_dotenv
from utils.instrument_utils import normalize_instrument_name, find_instrument_in_platform, get_available_instruments

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
    "NDX100": 0,  # Add adjustment1s for other CFDs as needed
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
    instruments = ['xauusd', 'gold', 'eurusd', 'gbpusd', 'usdjpy', 'us30', 'dji30', 'nas100', 'ndx100']
    has_instrument = any(instrument in message_lower for instrument in instruments)

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
        is_buy = parsed_signal.get('order_type', '').lower() == 'buy'

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
        logger.info("Using cached parsed signal")
        return parsed_signal_cache[message]

    # Pre-filter to avoid unnecessary API calls
    if not is_potential_trading_signal(message):
        logger.info("Message doesn't appear to be a valid trading signal, skipping API call")
        parsed_signal_cache[message] = None  # Cache the negative result
        return None

    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a trading signal parser. Always respond with a valid JSON object and nothing else."
                    },
                    {
                        "role": "user",
                        "content": f'''Parse the following trading signal and return a JSON object:

                        "{message}"

                        Rules:
                        1. The JSON object should have these fields: instrument, order_type, entry_point, stop_loss, and take_profits.
                        1.1 orderType should only return 'buy' or 'sell'.
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


                        Respond only with the JSON object or null, no additional text.'''
                    }
                ]
            }
        )
        content = response.json()["choices"][0]["message"]["content"].strip()
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

            # Ensure order_type is valid
            if result.get('order_type') not in ['buy', 'sell']:
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
        payload = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a trading signal parser. Always respond with a valid JSON object and nothing else."
                },
                {
                    "role": "user",
                    "content": f'''Parse the following trading signal and return a JSON object:

                    "{message}"

                    Rules:
                    1. The JSON object should have these fields: instrument, order_type, entry_point, stop_loss, and take_profits.
                    1.1 orderType should only return 'buy' or 'sell'.
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


                    Respond only with the JSON object or null, no additional text.'''
                }
            ]
        }

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

                    # Ensure order_type is valid
                    if result.get('order_type') not in ['buy', 'sell']:
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
    Find the matching instrument in the platform for the signal.

    Args:
        instruments_client: TradeLocker instruments client
        account: Account information dictionary
        parsed_signal: Parsed signal with normalized instrument name

    Returns:
        dict: Instrument data from the platform or None if not found
    """
    canonical_name = parsed_signal['instrument']

    # First try direct match with the canonical name
    instrument_data = await instruments_client.get_instrument_by_name_async(
        account['id'],
        account['accNum'],
        canonical_name
    )

    if instrument_data:
        logger.info(f"Found exact match for instrument {canonical_name}")
        return instrument_data

    # If not found, get available instruments and find a match
    available_instruments = await get_available_instruments(instruments_client, account)

    # Find the platform-specific instrument name using our utility
    platform_instrument = find_instrument_in_platform(canonical_name, available_instruments)

    if platform_instrument and platform_instrument != canonical_name:
        logger.info(f"Using platform instrument {platform_instrument} instead of {canonical_name}")

        # Get the instrument data using the platform-specific name
        instrument_data = await instruments_client.get_instrument_by_name_async(
            account['id'],
            account['accNum'],
            platform_instrument
        )

        if instrument_data:
            return instrument_data

    # If we still haven't found it, try some common variations as a last resort
    if canonical_name.endswith(".C") or canonical_name.endswith(".X") or canonical_name.endswith(".Z"):
        # Try without suffix
        base_name = canonical_name.split('.')[0]
        instrument_data = await instruments_client.get_instrument_by_name_async(
            account['id'],
            account['accNum'],
            base_name
        )
        if instrument_data:
            logger.info(f"Found match by removing suffix: {base_name}")
            return instrument_data
    elif not canonical_name.endswith(".C"):
        # Try with .C suffix
        instrument_data = await instruments_client.get_instrument_by_name_async(
            account['id'],
            account['accNum'],
            f"{canonical_name}.C"
        )
        if instrument_data:
            logger.info(f"Found match by adding .C suffix: {canonical_name}.C")
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
update_broker_adjustment('DJI30', 41850, 41855)