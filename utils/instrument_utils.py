import re
import time
import logging

logger = logging.getLogger(__name__)

# Global cache for instruments
_instruments_cache = {}


def normalize_instrument_name(instrument_name):
    """
    Normalize instrument names to canonical form.
    Maps common variants to standard names.

    Args:
        instrument_name (str): The instrument name to normalize

    Returns:
        str: Normalized instrument name
    """
    if not instrument_name:
        return None

    # Convert to uppercase for consistency
    instrument = instrument_name.upper()

    # Common mappings dictionary - expanded with Traders_HIVE specific mappings
    mappings = {
        # Indices
        "US30": "DJI30",
        "DOW": "DJI30",
        "DOW JONES": "DJI30",
        "DOWJONES": "DJI30",
        "DJI": "DJI30",
        "US500": "SPX500",
        "SP500": "SPX500",
        "S&P500": "SPX500",
        "S&P": "SPX500",
        "NAS100": "NDX100",
        "NASDAQ": "NDX100",
        "NASDAQ100": "NDX100",
        "NAS": "NDX100",
        "USTEC": "NDX100",

        # Metals
        "GOLD": "XAUUSD",
        "XAU": "XAUUSD",
        "SILVER": "XAGUSD",
        "XAG": "XAGUSD",

        # Oil
        "OIL": "XTIUSD",
        "CRUDE": "XTIUSD",
        "CRUDEOIL": "XTIUSD",
        "WTI": "XTIUSD",
        "BRENT": "XBRUSD",

        # Forex special cases
        "EURO": "EURUSD"
    }

    # Handle cases with additional text like "sell gold" or "buy nas100"
    for key, value in mappings.items():
        if key in instrument:
            return value

    # If it's already in canonical form, return as is
    if instrument in mappings.values():
        return instrument

    # For standard forex pairs, ensure proper format
    if len(instrument) == 6 and instrument.isalpha():
        # It's likely a forex pair like EURUSD
        return instrument

    # If nothing matches, return the original
    return instrument


def find_instrument_in_platform(canonical_name, available_instruments):
    """
    Find the platform-specific instrument name for a canonical instrument name.

    Args:
        canonical_name (str): Canonical instrument name (e.g., "DJI30")
        available_instruments (list): List of available instruments from the platform

    Returns:
        str: Platform-specific instrument name or canonical_name if not found
    """
    if not canonical_name or not available_instruments:
        return canonical_name

    # Direct platform mapping for common instruments
    platform_mappings = {
        "DJI30": ["DOW.C", "US30.C", "US30", "DJ30.C"],
        "NDX100": ["NAS100.C", "NASDAQ.C", "USTEC.C", "NDX.C"],
        "SPX500": ["SPX.C", "SP500.C", "S&P500.C"],
        "XAUUSD": ["GOLD.C", "XAU.C", "XAUUSD.C", "XAUUSD"],
        "XAGUSD": ["SILVER.C", "XAG.C", "XAGUSD.C", "XAGUSD"]
    }

    # Check if we have a direct mapping for this instrument
    if canonical_name in platform_mappings:
        possible_names = platform_mappings[canonical_name]

        # Check each possible platform name against available instruments
        for name in possible_names:
            for instrument in available_instruments:
                # Get name from instrument object
                instrument_name = instrument.get('name', '')
                if instrument_name == name:
                    logger.info(f"Found platform instrument {name} for {canonical_name}")
                    return name

    # If not found in mappings, search directly in available instruments
    for instrument in available_instruments:
        instrument_name = instrument.get('name', '')

        # Try exact match
        if instrument_name == canonical_name:
            return canonical_name

        # Try without suffix
        base_name = canonical_name.split('.')[0]
        if instrument_name == base_name:
            return base_name

        # Try with common suffixes
        for suffix in ['.C', '.X', '.Z']:
            if instrument_name == f"{canonical_name}{suffix}":
                return instrument_name

    # If still not found, return the canonical name
    logger.warning(f"Could not find platform instrument for {canonical_name}")
    return canonical_name


async def get_available_instruments(instruments_client, account):
    """
    Get available instruments for the account with caching.

    Args:
        instruments_client: TradeLocker instruments client
        account: Account information dictionary

    Returns:
        list: List of available instruments
    """
    # Create cache key for this account
    cache_key = f"{account['id']}:{account['accNum']}"

    # Return cached result if available and not too old (cache for 1 hour)
    if cache_key in _instruments_cache:
        cache_entry = _instruments_cache[cache_key]
        cache_time = cache_entry.get('time', 0)
        if time.time() - cache_time < 3600:  # 1 hour cache
            logger.debug(f"Using cached instruments list ({len(cache_entry['instruments'])} instruments)")
            return cache_entry['instruments']

    # Fetch instruments from API
    try:
        instruments = await instruments_client.get_instruments_async(
            account['id'],
            account['accNum']
        )

        if instruments:
            # Cache the result
            _instruments_cache[cache_key] = {
                'instruments': instruments,
                'time': time.time()
            }
            logger.info(f"Cached {len(instruments)} instruments from API")
            return instruments
        else:
            logger.warning("Failed to get instruments from API")
            # Return cached instruments if available (even if expired)
            if cache_key in _instruments_cache:
                return _instruments_cache[cache_key]['instruments']
            return []

    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")
        # Return cached instruments if available
        if cache_key in _instruments_cache:
            return _instruments_cache[cache_key]['instruments']
        return []


def extract_instrument_from_text(text):
    """
    Extract instrument name from text.
    Enhanced to handle text with emojis and Traders_HIVE specific formats.

    Args:
        text (str): The text to analyze

    Returns:
        str: Extracted canonical instrument name or None if not found
    """
    if not text:
        return None

    # Convert to lowercase for consistent matching
    text = text.lower()

    # Try to match common instrument identifiers
    patterns = [
        # Forex pairs
        r'\b(eur/?usd|gbp/?usd|usd/?jpy|aud/?usd|nzd/?usd|usd/?cad|usd/?chf|eur/?gbp|eur/?jpy)\b',

        # Stock indices
        r'\b(us30|dji30|dow|dow jones|spx500|sp500|s&p|nasdaq|nas100|ndx100)\b',

        # Commodities
        r'\b(gold|xauusd|silver|xagusd|oil|crude|wti|brent)\b'
    ]

    # Check each pattern
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            extracted = match.group(1)
            # Normalize to canonical form
            return normalize_instrument_name(extracted)

    # Special handling for Traders_HIVE format with US30 references
    if 'us30' in text:
        return 'DJI30'

    return None


def clear_instruments_cache():
    """Clear the instruments cache"""
    global _instruments_cache
    _instruments_cache.clear()
    logger.info("Instruments cache cleared")