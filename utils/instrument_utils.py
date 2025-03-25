import re
import logging
import asyncio

logger = logging.getLogger(__name__)

# Canonical instrument groups - each list contains ALL variations of the same instrument
# This ensures we can match any signal variation to any broker variation
INSTRUMENT_GROUPS = {
    'GOLD': ['GOLD', 'XAUUSD', 'XAU', 'GOLD.', 'XAUUSD.', 'GOLD/', 'XAU/', 'GOLD-', 'XAU-'],
    'SILVER': ['SILVER', 'XAGUSD', 'XAG', 'SILVER.', 'XAGUSD.', 'SILVER/', 'XAG/', 'SILVER-', 'XAG-'],
    'DOW_JONES': ['DOW', 'DJI30', 'US30', 'DOWJONES', 'DJ30', 'WALLST', 'DJI', 'DOW.', 'US30.', 'DOWJONES.', 'DJ.'],
    'NASDAQ': ['NDX100', 'NAS100', 'NASDAQ', 'NSDQ', 'TECH100', 'NAS', 'NASDAQ.', 'NAS100.', 'NDX.', 'TECH.'],
    'SP500': ['SP500', 'SPX', 'S&P', 'SP.', 'SPX.', 'S&P500', 'SP-', 'SPX-'],
    'EURUSD': ['EURUSD', 'EUR/USD', 'EUR'],
    'GBPUSD': ['GBPUSD', 'GBP/USD', 'GBP'],
    'USDJPY': ['USDJPY', 'USD/JPY', 'JPY'],
    'USDCHF': ['USDCHF', 'USD/CHF', 'CHF'],
    'AUDUSD': ['AUDUSD', 'AUD/USD', 'AUD'],
    'NZDUSD': ['NZDUSD', 'NZD/USD', 'NZD'],
    'USDCAD': ['USDCAD', 'USD/CAD', 'CAD'],
    # Add more as needed
}

# Build reverse lookup dictionary for fast matching
NICKNAME_TO_GROUP = {}
for group_name, nicknames in INSTRUMENT_GROUPS.items():
    for nickname in nicknames:
        NICKNAME_TO_GROUP[nickname] = group_name

# Platform-specific instrument name suffixes
PLATFORM_SUFFIXES = ['.C', '.Z', '.X', '+', '-', '', '_']


def normalize_instrument_name(name):
    """
    Normalize an instrument name to its canonical form.

    Args:
        name: Instrument name to normalize

    Returns:
        str: Canonical form of the instrument name
    """
    if not name:
        return name

    # Convert to uppercase for comparison
    name_upper = name.upper()

    # First try direct lookup in our reverse dictionary
    for nickname in NICKNAME_TO_GROUP.keys():
        if nickname == name_upper:
            group = NICKNAME_TO_GROUP[nickname]
            # Return the first nickname in the group as the canonical name
            return INSTRUMENT_GROUPS[group][0]

    # Next try prefix matching (e.g. "GOLD" matches "GOLD.C")
    for nickname in NICKNAME_TO_GROUP.keys():
        if name_upper.startswith(nickname):
            group = NICKNAME_TO_GROUP[nickname]
            return INSTRUMENT_GROUPS[group][0]

    # Then try substring matching for more flexibility
    for nickname in NICKNAME_TO_GROUP.keys():
        if nickname in name_upper:
            group = NICKNAME_TO_GROUP[nickname]
            return INSTRUMENT_GROUPS[group][0]

    # If it's a standard forex pair format but not in our predefined list
    if len(name_upper) == 6 and name_upper.isalpha():
        return name_upper

    # Remove any suffixes
    if '.' in name or '+' in name or '-' in name or '_' in name:
        # Extract base name by removing any suffix
        base_name = re.sub(r'[.+\-_].*$', '', name_upper)
        return base_name

    # If no matches or transformations, return the original in uppercase
    return name_upper


def extract_instrument_from_text(text):
    """
    Extract instrument name from a text message.

    Args:
        text: The text to extract from

    Returns:
        str: Canonical instrument name or None if not found
    """
    if not text:
        return None

    # Convert to lowercase for case-insensitive matching
    text_lower = text.lower()

    # Check for direct mentions of instruments from our groups
    for group, nicknames in INSTRUMENT_GROUPS.items():
        for nickname in nicknames:
            if nickname.lower() in text_lower:
                return INSTRUMENT_GROUPS[group][0]  # Return canonical name

    # Check for standard instrument patterns
    # Common forex pairs
    forex_regex = r'\b([a-z]{3}[/\-]?[a-z]{3})\b'
    forex_matches = re.findall(forex_regex, text_lower)

    for match in forex_matches:
        # Normalize match (remove slashes, dashes)
        normalized = match.replace('/', '').replace('-', '')

        # Check if it's in our mappings
        for group, nicknames in INSTRUMENT_GROUPS.items():
            if normalized.upper() in [nick.upper() for nick in nicknames]:
                return INSTRUMENT_GROUPS[group][0]  # Return canonical name

        # If not in mappings but looks like a valid instrument, return it uppercase
        if len(normalized) == 6:
            return normalized.upper()

    # No instrument found
    return None


async def get_available_instruments(instruments_client, account):
    """
    Get all available instruments for the account.

    Args:
        instruments_client: TradeLocker instruments client
        account: Account information

    Returns:
        list: List of available instruments
    """
    try:
        instruments = await instruments_client.get_instruments_async(
            account['id'],
            account['accNum']
        )

        if not instruments:
            logger.warning("No instruments found for account")
            return []

        return instruments
    except Exception as e:
        logger.error(f"Error getting available instruments: {e}")
        return []


def identify_instrument_group(instrument_name):
    """
    Identify which canonical instrument group a given instrument name belongs to.

    Args:
        instrument_name: The instrument name from the signal

    Returns:
        tuple: (group_name, nicknames) or (None, []) if no match
    """
    if not instrument_name:
        return None, []

    # Convert to uppercase for case-insensitive matching
    input_upper = instrument_name.upper()

    # First try direct lookup in our reverse dictionary
    for nickname in NICKNAME_TO_GROUP.keys():
        if nickname == input_upper:
            group = NICKNAME_TO_GROUP[nickname]
            return group, INSTRUMENT_GROUPS[group]

    # Next try prefix matching (e.g. "GOLD" matches "GOLD.C")
    for nickname in NICKNAME_TO_GROUP.keys():
        if input_upper.startswith(nickname):
            group = NICKNAME_TO_GROUP[nickname]
            return group, INSTRUMENT_GROUPS[group]

    # Then try substring matching for more flexibility
    for nickname in NICKNAME_TO_GROUP.keys():
        if nickname in input_upper:
            group = NICKNAME_TO_GROUP[nickname]
            return group, INSTRUMENT_GROUPS[group]

    # If it's a standard forex pair (e.g., AUDNZD) not in our predefined list
    if len(input_upper) == 6 and input_upper.isalpha():
        # Create a dynamic group for this forex pair
        group_name = input_upper
        return group_name, [input_upper, f"{input_upper[:3]}/{input_upper[3:]}"]

    # No match found
    return None, [instrument_name.upper()]  # Return original name as fallback


def score_instrument_match(instrument_name, target_nicknames):
    """
    Score how well a broker's instrument name matches our target nicknames.

    Args:
        instrument_name: Broker's instrument name
        target_nicknames: List of nicknames to check against

    Returns:
        int: Score from 0-100, higher is better match
    """
    name_upper = instrument_name.upper()

    # Exact match gets highest score
    if any(nick == name_upper for nick in target_nicknames):
        return 100

    # Prefix match (e.g., "XAUUSD" at the start of "XAUUSD.X")
    if any(name_upper.startswith(nick) for nick in target_nicknames):
        return 90

    # Contains match (e.g., "XAUUSD" anywhere in the name)
    if any(nick in name_upper for nick in target_nicknames):
        return 80

    # Clean name comparison (remove special chars)
    clean_name = re.sub(r'[^A-Z0-9]', '', name_upper)
    if any(re.sub(r'[^A-Z0-9]', '', nick) == clean_name for nick in target_nicknames):
        return 70

    # No match
    return 0


def find_instrument_in_platform(canonical_name, available_instruments):
    """
    Find a platform-specific instrument name based on canonical name.
    Enhanced with keyword-based matching for flexibility across brokers.

    Args:
        canonical_name: Canonical instrument name (e.g., 'DJI30')
        available_instruments: List of available instruments from the platform

    Returns:
        str: Platform-specific instrument name or None if not found
    """
    if not canonical_name or not available_instruments:
        return None

    # Identify which instrument group the canonical name belongs to
    group_name, target_nicknames = identify_instrument_group(canonical_name)

    if not group_name:
        # If we can't identify a group, just use the canonical name
        target_nicknames = [canonical_name]

    # Score and sort all available instruments
    scored_instruments = []
    for instrument in available_instruments:
        instr_name = instrument.get('name', '')
        score = score_instrument_match(instr_name, target_nicknames)
        if score > 0:
            scored_instruments.append((score, instr_name))

    # Sort by score descending
    scored_instruments.sort(reverse=True)

    # Return the best match, or None if no matches
    return scored_instruments[0][1] if scored_instruments else None


def match_instrument_by_context(text, open_positions):
    """
    Try to match a specific instrument based on context clues in the text.

    Args:
        text: Text message
        open_positions: List of current open positions

    Returns:
        str: Best matching instrument name or None
    """
    if not text or not open_positions:
        return None

    text_lower = text.lower()

    # Check for buy/sell direction
    is_buy = any(kw in text_lower for kw in ['buy', 'long', 'bullish'])
    is_sell = any(kw in text_lower for kw in ['sell', 'short', 'bearish'])

    # Filter positions by direction if specified
    filtered_positions = []
    if is_buy and not is_sell:
        filtered_positions = [p for p in open_positions if p.get('side', '').lower() == 'buy']
    elif is_sell and not is_buy:
        filtered_positions = [p for p in open_positions if p.get('side', '').lower() == 'sell']
    else:
        filtered_positions = open_positions

    if not filtered_positions:
        return None

    # Extract prices from the message
    prices = extract_price_from_text(text_lower)

    # If prices found, try to match with position prices
    if prices:
        for position in filtered_positions:
            entry_price = float(position.get('entry_price', 0))
            # Check if any of the extracted prices are close to the entry price
            for price in prices:
                # Use a small tolerance (0.1%)
                tolerance = entry_price * 0.001
                if abs(entry_price - price) <= tolerance:
                    return position.get('instrument_name')

    # If still no match and we have exactly one position, use that
    if len(filtered_positions) == 1:
        return filtered_positions[0].get('instrument_name')

    # No clear match found
    return None


def extract_price_from_text(text):
    """
    Extract price values from text.

    Args:
        text: Text to extract from

    Returns:
        list: List of extracted price values as floats
    """
    if not text:
        return []

    # Look for price patterns
    price_regex = r'\b(\d+\.\d+)\b'  # Basic price format like 1.2345
    price_matches = re.findall(price_regex, text)

    # Convert matches to floats
    return [float(p) for p in price_matches]