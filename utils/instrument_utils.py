"""
Utility functions for instrument name normalization and detection.
Centralizes the logic for handling different symbol representations.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Mapping of instrument aliases to their canonical names
# This is used for internal normalization of signal provider names
INSTRUMENT_ALIASES = {
    # Indices
    "US30": "DJI30",
    "DOW.C": "DJI30",
    "DOW.X": "DJI30",
    "DOW.Z": "DJI30",
    "DOW": "DJI30",

    # Nasdaq variations
    "NAS100": "NDX100",
    "NSDQ": "NDX100",
    "NSDQ.C": "NDX100",
    "NSDQ.X": "NDX100",
    "NSDQ.Z": "NDX100",

    # Commodities
    "GOLD": "XAUUSD",
    "SILVER": "XAGUSD"
}

# Platform-specific instrument codes based on your screenshots
# Maps canonical names to possible instrument names in your platform
PLATFORM_INSTRUMENT_MAP = {
    "NDX100": ["NDX100", "NAS100", "NSDQ.C"],
    "DJI30": ["DJI30", "US30", "DOW.C", "DOW"],
    "XAUUSD": ["XAUUSD", "GOLD"],
    "XAGUSD": ["XAGUSD", "SILVER"]
}

# Standard forex pairs and commodity pairs that might have suffixes
STANDARD_INSTRUMENTS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF",
    "XAUUSD", "XAGUSD", "DJI30", "NDX100"
]

# Extended regex patterns for instrument detection
INSTRUMENT_PATTERNS = [
    # Forex pairs with optional suffix
    r"\b(eur/?usd(?:\.[cxz])?)\b",
    r"\b(gbp/?usd(?:\.[cxz])?)\b",
    r"\b(usd/?jpy(?:\.[cxz])?)\b",
    r"\b(aud/?usd(?:\.[cxz])?)\b",
    r"\b(usd/?cad(?:\.[cxz])?)\b",
    r"\b(nzd/?usd(?:\.[cxz])?)\b",
    r"\b(usd/?chf(?:\.[cxz])?)\b",

    # Commodities with optional suffix
    r"\b(gold|xauusd(?:\.[cxz])?)\b",
    r"\b(silver|xagusd(?:\.[cxz])?)\b",

    # Indices with various aliases and optional suffixes
    r"\b(dji30|us30|dow(?:\.?[cxz])?)\b",
    r"\b(ndx100|nas100|nsdq(?:\.[cxz])?)\b"
]


def normalize_instrument_name(instrument_name):
    """
    Normalize various instrument name formats to a standard canonical format.

    Args:
        instrument_name (str): The instrument name to normalize

    Returns:
        str: The normalized instrument name
    """
    if not instrument_name:
        return None

    # Convert to uppercase and remove any whitespace
    instr = instrument_name.upper().replace(" ", "")

    # Remove slash if present
    instr = instr.replace("/", "")

    # Check direct mapping in aliases dictionary
    if instr in INSTRUMENT_ALIASES:
        return INSTRUMENT_ALIASES[instr]

    # Handle forex pairs and other instruments with suffixes (.C, .X, .Z)
    for std_instr in STANDARD_INSTRUMENTS:
        if instr.startswith(std_instr + "."):
            return std_instr

    # If we couldn't normalize it but it matches a basic pattern, return as is
    return instr


def find_instrument_in_platform(canonical_name, available_instruments):
    """
    Find the matching instrument name in your platform's available instruments.

    Args:
        canonical_name (str): The canonical instrument name (e.g., "NDX100")
        available_instruments (list): List of available instruments from API

    Returns:
        str: The matching platform instrument name or None if not found
    """
    if not canonical_name or not available_instruments:
        return None

    # Check if the canonical name itself is available
    if canonical_name in available_instruments:
        return canonical_name

    # Get possible platform names for this canonical name
    possible_names = PLATFORM_INSTRUMENT_MAP.get(canonical_name, [])

    # Check each possible name against available instruments
    for name in possible_names:
        if name in available_instruments:
            logger.info(f"Found match: {name} for canonical name {canonical_name}")
            return name

    # For forex pairs, try with all possible suffixes
    if canonical_name in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"]:
        suffixes = ["", ".C", ".X", ".Z"]
        for suffix in suffixes:
            test_name = canonical_name + suffix
            if test_name in available_instruments:
                logger.info(f"Found forex match with suffix: {test_name}")
                return test_name

    # If no exact match, try case-insensitive matching
    canonical_lower = canonical_name.lower()
    for instr in available_instruments:
        if instr.lower() == canonical_lower:
            logger.info(f"Found case-insensitive match: {instr}")
            return instr

    logger.warning(f"No match found for {canonical_name}")
    return None


def extract_instrument_from_text(text):
    """
    Extract instrument name from text using comprehensive regex patterns.

    Args:
        text (str): The text to extract instrument from

    Returns:
        str: Normalized instrument name or None if not found
    """
    if not text:
        return None

    text_lower = text.lower()

    for pattern in INSTRUMENT_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            # Extract the matched instrument and normalize it
            matched_instr = match.group(1).upper()
            return normalize_instrument_name(matched_instr)

    return None


def get_instrument_display_names(canonical_name):
    """
    Get all possible display names for a canonical instrument name.

    Args:
        canonical_name (str): The canonical instrument name (e.g., DJI30)

    Returns:
        list: List of all possible display names
    """
    if not canonical_name:
        return []

    # Start with the canonical name itself
    display_names = [canonical_name]

    # Add all aliases that map to this canonical name
    for alias, canon in INSTRUMENT_ALIASES.items():
        if canon == canonical_name:
            display_names.append(alias)

    # Add platform-specific names
    if canonical_name in PLATFORM_INSTRUMENT_MAP:
        display_names.extend(PLATFORM_INSTRUMENT_MAP[canonical_name])

    # Remove duplicates while preserving order
    unique_names = []
    for name in display_names:
        if name not in unique_names:
            unique_names.append(name)

    return unique_names


# Cache of available instruments from the API
_cached_instruments = None
_instrument_cache_time = 0

async def get_available_instruments(instruments_client, account, refresh=False):
    """
    Get available instruments from the API with caching.

    Args:
        instruments_client: The TradeLocker instruments client
        account: Account information dictionary
        refresh (bool): Whether to force refresh the cache

    Returns:
        list: List of available instrument names
    """
    global _cached_instruments, _instrument_cache_time
    import time

    current_time = time.time()
    cache_ttl = 3600  # 1 hour cache

    # Return cached result if available and not expired
    if not refresh and _cached_instruments and current_time - _instrument_cache_time < cache_ttl:
        return _cached_instruments

    try:
        instruments = await instruments_client.get_instruments_async(
            account_id=account['id'],
            acc_num=account['accNum']
        )

        if not instruments:
            logger.warning("No instruments returned from API")
            return []

        instrument_names = [instr.get('name') for instr in instruments]

        # Update cache
        _cached_instruments = instrument_names
        _instrument_cache_time = current_time

        logger.info(f"Cached {len(instrument_names)} instruments from API")
        return instrument_names

    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")
        return _cached_instruments or []  # Return cached if available, otherwise empty list