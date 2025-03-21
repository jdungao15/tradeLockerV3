import asyncio
import risk_config
import requests
import aiohttp
import json
import os
import logging
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Exchange rate cache to reduce API calls
_exchange_rate_cache = {}
_exchange_rate_ttl = {}
_cache_duration = 3600  # 1 hour cache for exchange rates


# Exchange rate
@lru_cache(maxsize=128)
def get_exchange_rate(base: str, quote: str) -> float:
    """
    Get exchange rate with caching and error handling.

    Args:
        base: Base currency code
        quote: Quote currency code

    Returns:
        float: Exchange rate

    Raises:
        ValueError: If exchange rate cannot be fetched
    """
    cache_key = f"{base}:{quote}"

    # Check cache first
    import time
    current_time = time.time()
    if cache_key in _exchange_rate_cache and current_time < _exchange_rate_ttl.get(cache_key, 0):
        return _exchange_rate_cache[cache_key]

    try:
        host = "https://api.frankfurter.app"
        amount = 1
        url = f"{host}/latest?amount={amount}&from={base}&to={quote}"

        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if quote not in data.get('rates', {}):
            raise ValueError(f"Exchange rate for {base} to {quote} not found")

        rate = data['rates'][quote]

        # Cache the result
        _exchange_rate_cache[cache_key] = rate
        _exchange_rate_ttl[cache_key] = current_time + _cache_duration

        return rate
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching exchange rate: {e}")

        # If we have cached data, use it even if expired (better than nothing)
        if cache_key in _exchange_rate_cache:
            logger.warning(f"Using expired exchange rate for {base}:{quote} due to API error")
            return _exchange_rate_cache[cache_key]

        # For USD/EUR as base currencies to common trading currencies, use fallback rates
        fallback_rates = {
            "USD:EUR": 0.92,
            "EUR:USD": 1.09,
            "USD:JPY": 150.0,
            "EUR:JPY": 162.0,
            "USD:GBP": 0.78,
            "EUR:GBP": 0.85,
            "USD:AUD": 1.52,
            "USD:CAD": 1.35,
            "USD:CHF": 0.90
        }

        if cache_key in fallback_rates:
            logger.warning(f"Using fallback exchange rate for {cache_key}")
            return fallback_rates[cache_key]

        # Last resort for USD-based pairs
        if base == "USD":
            logger.warning(f"Using 1.0 as fallback exchange rate for USD to {quote}")
            return 1.0

        raise ValueError(f"Could not determine exchange rate for {base} to {quote}") from e


# Async version of exchange rate function
async def get_exchange_rate_async(base: str, quote: str) -> float:
    """
    Get exchange rate asynchronously with caching and error handling.

    Args:
        base: Base currency code
        quote: Quote currency code

    Returns:
        float: Exchange rate

    Raises:
        ValueError: If exchange rate cannot be fetched
    """
    cache_key = f"{base}:{quote}"

    # Check cache first
    import time
    current_time = time.time()
    if cache_key in _exchange_rate_cache and current_time < _exchange_rate_ttl.get(cache_key, 0):
        return _exchange_rate_cache[cache_key]

    try:
        host = "https://api.frankfurter.app"
        amount = 1
        url = f"{host}/latest?amount={amount}&from={base}&to={quote}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                response.raise_for_status()
                data = await response.json()

                if quote not in data.get('rates', {}):
                    raise ValueError(f"Exchange rate for {base} to {quote} not found")

                rate = data['rates'][quote]

                # Cache the result
                _exchange_rate_cache[cache_key] = rate
                _exchange_rate_ttl[cache_key] = current_time + _cache_duration

                return rate
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Error fetching exchange rate: {e}")

        # If we have cached data, use it even if expired (better than nothing)
        if cache_key in _exchange_rate_cache:
            logger.warning(f"Using expired exchange rate for {base}:{quote} due to API error")
            return _exchange_rate_cache[cache_key]

        # Fall back to synchronous version for better error handling
        return get_exchange_rate(base, quote)


# Calculate stop loss in pips
def calculate_stop_loss_pips(stop_loss: float, entry_point: float, instrument: dict) -> float:
    """
    Calculate stop loss in pips based on instrument type.

    Args:
        stop_loss: Stop loss price
        entry_point: Entry point price
        instrument: Instrument data dictionary

    Returns:
        float: Stop loss distance in pips
    """
    try:
        # Handle instrument name with suffixes (.C, .X, .Z)
        instrument_name = instrument["name"]
        base_name = instrument_name.split('.')[0]  # Remove any suffix

        if base_name.endswith("JPY"):
            return abs(stop_loss - entry_point) / 0.01
        elif instrument['type'] == "FOREX":
            return abs(stop_loss - entry_point) / 0.0001
        return abs(stop_loss - entry_point)
    except Exception as e:
        logger.error(f"Error calculating stop loss pips: {e}")
        # Safe fallback: Use a default calculation
        return abs(stop_loss - entry_point) * 10000
# Update the calculate_pip_value function in core/risk_management.py

def calculate_pip_value(instrument: dict) -> float:
    """
    Calculate pip value for a given instrument.
    Args:
        instrument: Instrument data dictionary
    Returns:
        float: Value of 1 pip in account currency
    Raises:
        ValueError: If unable to calculate pip value
    """
    try:
        # Handle instrument name with suffixes (.C, .X, .Z)
        instrument_name = instrument["name"]
        base_name = instrument_name.split('.')[0]  # Remove any suffix

        # Add explicit mapping for DOW to DJI30
        if base_name == "DOW":
            base_name = "DJI30"  # Treat DOW as DJI30 for pip value lookup
            logger.info(f"Treating {instrument_name} as DJI30 for pip calculations")

        if instrument["type"] == "FOREX":
            base_currency = base_name[:3]
            quote_currency = base_name[3:]
            exchange_rate = get_exchange_rate(base_currency, quote_currency)
            pip_value = 0.01 / exchange_rate if base_name.endswith("JPY") else 0.0001 / exchange_rate
        elif instrument["type"] == "EQUITY_CFD":
            pip_values = {
                "NDX100": 20,
                "DJI30": 5,
                "XAUUSD": 100
            }
            # Check if the base name (without suffix) is in the pip_values dictionary
            if base_name not in pip_values:
                logger.error(f"Invalid index type: {base_name} from {instrument_name}")
                raise ValueError(f"Invalid index type: {base_name}")
            pip_value = pip_values[base_name]
            logger.info(f"Using pip value {pip_value} for {instrument_name} (base: {base_name})")
        else:
            raise ValueError(f"Unsupported instrument type: {instrument['type']}")
        return pip_value
    except Exception as e:
        logger.error(f"Error calculating pip value: {e}")
        # Provide fallbacks for common instruments
        fallbacks = {
            "EURUSD": 10,
            "GBPUSD": 10,
            "USDJPY": 9.33,
            "XAUUSD": 100,
            "NDX100": 20,
            "DJI30": 5,
            "DOW": 5  # Add DOW to fallbacks too
        }

        # Try matching the base name (without suffix)
        base_name = instrument["name"].split('.')[0]
        if base_name in fallbacks:
            logger.warning(f"Using fallback pip value for {base_name}: {fallbacks[base_name]}")
            return fallbacks[base_name]

        # For other forex pairs, use a safe default
        if instrument["type"] == "FOREX":
            logger.warning(f"Using default pip value for {instrument['name']}")
            return 10.0
        raise ValueError(f"Cannot determine pip value for {instrument['name']}")

# Determine the risk percentage based on account tiers
def determine_risk_percentage(account_balance: float, instrument: dict, reduced_risk: bool = False) -> float:
    """
    Determine risk percentage based on account balance, instrument, and risk flag.
    Uses configurable risk settings from risk_config.

    Args:
        account_balance: Current account balance
        instrument: Instrument data dictionary
        reduced_risk: Flag indicating if the signal suggests reduced risk

    Returns:
        float: Risk percentage (e.g., 0.02 for 2%)
    """
    try:
        # Determine instrument type for risk configuration
        instrument_name = instrument.get("name", "")
        instrument_type = instrument.get("type", "")

        # Special case for XAUUSD (Gold)
        if instrument_name == "XAUUSD":
            risk_percentage = risk_config.get_risk_percentage("XAUUSD", reduced_risk)
            logger.info(f"Using XAUUSD risk setting: {risk_percentage * 100:.2f}%")
            return risk_percentage

        # For other CFD instruments
        if instrument_type == "EQUITY_CFD":
            risk_percentage = risk_config.get_risk_percentage("CFD", reduced_risk)
            logger.info(f"Using CFD risk setting: {risk_percentage * 100:.2f}%")
            return risk_percentage

        # Default to forex risk settings
        risk_percentage = risk_config.get_risk_percentage("FOREX", reduced_risk)
        logger.info(f"Using FOREX risk setting: {risk_percentage * 100:.2f}%")
        return risk_percentage

    except Exception as e:
        logger.error(f"Error determining risk percentage: {e}")
        # Safe fallback: Use a conservative risk percentage
        return 0.005 if reduced_risk else 0.01  # 0.5% (reduced) or 1% as safe defaults


# Main function to calculate position size
# Update this function in core/risk_management.py

def calculate_position_size(
        instrument: dict,
        entry_point: float,
        stop_loss: float,
        take_profits: list,
        account: dict,
        reduced_risk: bool = False
) -> tuple:
    """
    Calculate position size based on risk management parameters.

    Args:
        instrument: Instrument data dictionary
        entry_point: Entry point price
        stop_loss: Stop loss price
        take_profits: List of take profit prices
        account: Account data dictionary
        reduced_risk: Flag indicating if the signal suggests reduced risk

    Returns:
        tuple: (list of position sizes, total risk amount)
    """
    try:
        # Ensure we have numeric data
        account_balance = float(account['accountBalance'])
        entry_point = float(entry_point)
        stop_loss = float(stop_loss)

        # Convert take_profits to a list of floats
        take_profits = [float(tp) for tp in take_profits]

        # Determine the risk percentage based on account tiers, instrument type, and risk flag
        risk_percentage = determine_risk_percentage(account_balance, instrument, reduced_risk)

        # Calculate the pip value for the instrument
        pip_value = calculate_pip_value(instrument)

        # Calculate the total amount you are willing to risk
        risk_amount = account_balance * risk_percentage
        stop_loss_pips = calculate_stop_loss_pips(stop_loss, entry_point, instrument)

        # Convert risk amount to base currency if necessary
        converted_risk_amount = risk_amount
        # Extract base name without suffix
        instrument_name = instrument['name'].split('.')[0]

        if instrument['type'] == "FOREX":
            base_currency = instrument_name[:3]

            # MAJOR PAIRS
            if base_currency != "USD" and "USD" in instrument_name:
                conversion_rate = get_exchange_rate("USD", base_currency)
                converted_risk_amount = risk_amount * conversion_rate
            elif "USD" not in instrument_name:
                # MINOR PAIRS
                conversion_rate_to_usd = get_exchange_rate(base_currency, "USD")
                converted_risk_amount = risk_amount / conversion_rate_to_usd

        # Calculate position size based on instrument type
        if instrument['type'] == "EQUITY_CFD":
            # For CFD instruments, use the last 3 take profits
            if len(take_profits) > 3:
                logger.info(f"For CFD instrument {instrument_name}, using only the last 3 take profits")
                filtered_take_profits = take_profits[-3:]  # Get last 3 take profits
            else:
                filtered_take_profits = take_profits  # Use all if less than 3

            # Calculate position size for the selected take profits
            total_pos_in_lots = converted_risk_amount / (stop_loss_pips * pip_value)

            # Equal distribution for all 3 take profits
            position_per_tp = total_pos_in_lots / 3

            # Create position sizes list with the right structure
            position_sizes = []
            if len(take_profits) > 3:
                # Add zeros for take profits we're not using
                position_sizes = [0.0] * (len(take_profits) - 3)
                # Add actual position sizes for the last 3 take profits
                position_sizes.extend([round(position_per_tp, 2) for _ in range(3)])
            elif len(take_profits) == 3:
                # If exactly 3 take profits, use equal distribution
                position_sizes = [round(position_per_tp, 2) for _ in range(3)]
            elif len(take_profits) < 3:
                # If less than 3 take profits, distribute evenly
                position_per_tp = total_pos_in_lots / len(take_profits)
                position_sizes = [round(position_per_tp, 2) for _ in take_profits]

        else:
            # For forex and other instruments using lot sizes
            total_pos_in_units = converted_risk_amount / (stop_loss_pips * pip_value)
            total_pos_in_lots = total_pos_in_units / 100_000
            position_size_per_tp = round(total_pos_in_lots / len(take_profits),
                                         2 if instrument_name.endswith("JPY") else 1)
            position_sizes = [position_size_per_tp for _ in take_profits]

        logger.info(f"Calculated position sizes: {position_sizes}, Risk amount: {risk_amount}")
        return position_sizes, round(risk_amount)

    except Exception as e:
        logger.error(f"Error calculating position size: {e}", exc_info=True)
        # Safe fallback: Use very small position sizes
        min_position = 0.01  # Minimum position size
        position_sizes = [min_position for _ in take_profits]

        # Estimate risk based on small position sizes
        est_risk = float(account['accountBalance']) * (0.0025 if reduced_risk else 0.005)  # Estimate 0.25% or 0.5% risk

        logger.warning(f"Using fallback position sizes due to error: {position_sizes}")
        return position_sizes, round(est_risk)

# Clear exchange rate cache
def clear_exchange_rate_cache():
    """Clear the exchange rate cache"""
    _exchange_rate_cache.clear()
    _exchange_rate_ttl.clear()
    get_exchange_rate.cache_clear()  # Clear lru_cache