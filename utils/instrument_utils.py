import re
import logging
import asyncio

logger = logging.getLogger(__name__)

# Mappings between common instrument names and their canonical forms
INSTRUMENT_MAPPINGS = {
    # Forex major pairs
    'eurusd': 'EURUSD',
    'eur/usd': 'EURUSD',
    'euro': 'EURUSD',
    'gbpusd': 'GBPUSD',
    'gbp/usd': 'GBPUSD',
    'pound': 'GBPUSD',
    'usdjpy': 'USDJPY',
    'usd/jpy': 'USDJPY',
    'dollar yen': 'USDJPY',
    'audusd': 'AUDUSD',
    'aud/usd': 'AUDUSD',
    'aussie': 'AUDUSD',
    'nzdusd': 'NZDUSD',
    'nzd/usd': 'NZDUSD',
    'kiwi': 'NZDUSD',

    # Commodities
    'gold': 'XAUUSD',
    'xauusd': 'XAUUSD',
    'xau/usd': 'XAUUSD',
    'silver': 'XAGUSD',
    'xagusd': 'XAGUSD',
    'xag/usd': 'XAGUSD',

    # Indices
    'us30': 'DJI30',
    'dow': 'DJI30',
    'dow jones': 'DJI30',
    'wall street': 'DJI30',
    'dji30': 'DJI30',
    'nas100': 'NDX100',
    'nasdaq': 'NDX100',
    'ndx100': 'NDX100',
    'us tech': 'NDX100'
}

# Platform-specific instrument name suffixes
PLATFORM_SUFFIXES = ['.C', '.Z', '.X', '']


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

    # Convert to lowercase for comparison
    name_lower = name.lower()

    # Remove any slashes or dashes
    normalized = name_lower.replace('/', '').replace('-', '')

    # Check if it's in our mappings
    if normalized in INSTRUMENT_MAPPINGS:
        return INSTRUMENT_MAPPINGS[normalized]

    # Try common aliases
    for alias, canonical in INSTRUMENT_MAPPINGS.items():
        if name_lower == alias:
            return canonical

    # If it's not in our mappings, return the original in uppercase
    # after removing any suffixes
    if '.' in name:
        base_name = name.split('.')[0].upper()
        return base_name

    return name.upper()


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

    # Check for direct mentions of instruments from our mapping
    for key, value in INSTRUMENT_MAPPINGS.items():
        if key in text_lower:
            return value

    # Check for standard instrument patterns
    # Common forex pairs
    forex_regex = r'\b([a-z]{3}[/\-]?[a-z]{3})\b'
    forex_matches = re.findall(forex_regex, text_lower)

    for match in forex_matches:
        # Normalize match (remove slashes, dashes)
        normalized = match.replace('/', '').replace('-', '')

        # Check if it's in our mappings
        if normalized in INSTRUMENT_MAPPINGS:
            return INSTRUMENT_MAPPINGS[normalized]

        # If not in mappings but looks like a valid instrument, return it uppercase
        if len(normalized) == 6:
            return normalized.upper()

    # Check for precious metals (XAU/USD, XAG/USD)
    metals_regex = r'\b(xau[/\-]?usd|xag[/\-]?usd)\b'
    metals_matches = re.findall(metals_regex, text_lower)

    for match in metals_matches:
        normalized = match.replace('/', '').replace('-', '')
        return normalized.upper()

    # Check for indices mentions
    indices_regex = r'\b(us30|nas100|sp500|dji30|ndx100)\b'
    indices_matches = re.findall(indices_regex, text_lower)

    for match in indices_matches:
        if match in INSTRUMENT_MAPPINGS:
            return INSTRUMENT_MAPPINGS[match]
        else:
            return match.upper()

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


def find_instrument_in_platform(canonical_name, available_instruments):
    """
    Find a platform-specific instrument name based on canonical name.

    Args:
        canonical_name: Canonical instrument name (e.g., 'DJI30')
        available_instruments: List of available instruments from the platform

    Returns:
        str: Platform-specific instrument name or None if not found
    """
    if not canonical_name or not available_instruments:
        return None

    # Try exact match first
    for instrument in available_instruments:
        if instrument.get('name') == canonical_name:
            return canonical_name

    # Try with common suffixes (.C, .X, etc.)
    for suffix in PLATFORM_SUFFIXES:
        instrument_name = f"{canonical_name}{suffix}"

        for instrument in available_instruments:
            if instrument.get('name') == instrument_name:
                return instrument_name

    # Try common mappings
    if canonical_name == 'DJI30':
        alternatives = ['DOW.C', 'DOW', 'US30.C', 'US30']

        for alt in alternatives:
            for instrument in available_instruments:
                if instrument.get('name') == alt:
                    return alt

    if canonical_name == 'NDX100':
        alternatives = ['NAS100.C', 'NAS100', 'NASDAQ.C', 'NASDAQ']

        for alt in alternatives:
            for instrument in available_instruments:
                if instrument.get('name') == alt:
                    return alt

    # No match found
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