import asyncio
import risk_config
import requests
import aiohttp
import json
import os
import logging
import re
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
    Enhanced to handle various broker naming conventions.

    Args:
        stop_loss: Stop loss price
        entry_point: Entry point price
        instrument: Instrument data dictionary

    Returns:
        float: Stop loss distance in pips
    """
    try:
        # Extract instrument name and clean it
        instrument_name = instrument["name"].upper()
        base_name = re.sub(r'[.+\-_].*$', '', instrument_name)

        logger.debug(f"Calculating stop loss pips for {instrument_name} (base: {base_name}), " +
                     f"Entry: {entry_point}, SL: {stop_loss}")

        price_difference = abs(stop_loss - entry_point)

        # Check for JPY pairs
        if "JPY" in base_name:
            pips = price_difference / 0.01
            logger.debug(f"JPY pair detected. Price diff: {price_difference}, Pips: {pips}")
            return pips

        # Check for Gold/XAUUSD
        if "XAU" in base_name or "GOLD" in base_name:
            pips = price_difference / 0.1
            logger.debug(f"Gold detected. Price diff: {price_difference}, Pips: {pips}")
            return pips

        # Check for Silver/XAGUSD
        if "XAG" in base_name or "SILVER" in base_name:
            pips = price_difference / 0.01
            logger.debug(f"Silver detected. Price diff: {price_difference}, Pips: {pips}")
            return pips

        # Check for indices
        if any(idx in base_name for idx in ["DOW", "DJI", "US30", "NDX", "NAS", "SPX", "SP500"]):
            pips = price_difference / 1.0
            logger.debug(f"Index detected. Price diff: {price_difference}, Pips: {pips}")
            return pips

        # Default forex calculation
        if instrument['type'] == "FOREX" or (len(base_name) == 6 and base_name.isalpha()):
            pips = price_difference / 0.0001
            logger.debug(f"Standard forex pair. Price diff: {price_difference}, Pips: {pips}")
            return pips

        # Default for other instrument types
        logger.debug(f"Using default pip calculation for {instrument_name}. Price diff: {price_difference}")
        return price_difference * 10000  # Safe multiplication for standard forex

    except Exception as e:
        logger.error(f"Error calculating stop loss pips: {e}", exc_info=True)
        # Safe fallback: Use a default calculation
        return abs(stop_loss - entry_point) * 10000

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
    Calculate position size based on risk management parameters with correctly distributed risk.
    Total risk is split across all take profit positions, with proper scaling for Gold.

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
        take_profits = [float(tp) for tp in take_profits]

        # Get number of take profit positions
        num_positions = len(take_profits)
        if num_positions == 0:
            num_positions = 1  # Avoid division by zero

        # Extract instrument information and clean name
        instrument_name = instrument['name'].upper()
        base_name = re.sub(r'[.+\-_].*$', '', instrument_name)

        # Determine risk percentage based on account tiers, instrument type, and risk flag
        risk_percentage = determine_risk_percentage(account_balance, instrument, reduced_risk)

        # Calculate total risk amount (NOT per position but TOTAL)
        total_risk_amount = account_balance * risk_percentage

        # Calculate risk per position (divide total risk by number of positions)
        risk_per_position = total_risk_amount / num_positions

        logger.info(
            f"Account: ${account_balance}, Risk: {risk_percentage * 100:.2f}%, Total risk: ${total_risk_amount:.2f}")
        logger.info(f"Positions: {num_positions}, Risk per position: ${risk_per_position:.2f}")

        # Calculate stop loss distance in absolute terms
        sl_distance = abs(entry_point - stop_loss)
        logger.info(f"Entry: {entry_point}, SL: {stop_loss}, Distance: {sl_distance}")

        # IDENTIFY INSTRUMENT TYPE
        is_forex = False
        is_jpy_pair = False
        is_gold = False
        is_silver = False
        is_us30 = False
        is_nas100 = False

        # Gold detection
        if "XAU" in base_name or "GOLD" in base_name:
            is_gold = True
            logger.info(f"Identified {instrument_name} as GOLD")

        # Silver detection
        elif "XAG" in base_name or "SILVER" in base_name:
            is_silver = True
            logger.info(f"Identified {instrument_name} as SILVER")

        # US30/DOW detection
        elif any(idx in base_name for idx in ["DOW", "DJI", "US30"]):
            is_us30 = True
            logger.info(f"Identified {instrument_name} as US30/DOW")

        # NASDAQ detection
        elif any(idx in base_name for idx in ["NAS", "NDX", "NASDAQ", "NSDQ"]):
            is_nas100 = True
            logger.info(f"Identified {instrument_name} as NASDAQ")

        # Forex detection
        elif (len(base_name) == 6 and base_name.isalpha()):
            is_forex = True
            is_jpy_pair = "JPY" in base_name
            logger.info(f"Identified {instrument_name} as Forex pair (JPY: {is_jpy_pair})")

        # CALCULATE POSITION SIZE BASED ON INSTRUMENT TYPE

        # For Gold/XAUUSD - CORRECTED FORMULA WITH PROPER SCALING
        if is_gold:
            # GOLD CALCULATION WITH CORRECT SCALING:
            # Key insight: 0.01 lot (1 micro lot) in Gold = $1 risk per $1 price move
            # So if we have a 4-point SL and $125 risk, we need:
            # $125 / $4 = 31.25 micro lots = 0.31 lots

            # First calculate micro lots
            micro_lots = risk_per_position / sl_distance

            # Convert to standard lots (divide by 100)
            lot_size = micro_lots / 100

            logger.info(
                f"GOLD calculation: ${risk_per_position} / {sl_distance} = {micro_lots} micro lots = {lot_size:.2f} lots")

        # For Silver/XAGUSD
        elif is_silver:
            # SILVER CALCULATION with similar scaling to Gold
            micro_lots = risk_per_position / (sl_distance * 0.5)  # Silver is ~half the value of Gold
            lot_size = micro_lots / 100
            logger.info(
                f"SILVER calculation: ${risk_per_position} / ({sl_distance} * 0.5) = {micro_lots} micro lots = {lot_size:.2f} lots")

        # For US30/DOW Index
        elif is_us30:
            # US30 CALCULATION:
            # 0.01 lot (1 micro lot) = $0.1 risk per point
            micro_lots = risk_per_position / (sl_distance * 0.05)
            lot_size = micro_lots / 100
            logger.info(
                f"US30 calculation: ${risk_per_position} / ({sl_distance} * 0.1) = {micro_lots} micro lots = {lot_size:.2f} lots")

        # For NASDAQ/NAS100
        elif is_nas100:
            # NAS100 CALCULATION:
            # 0.01 lot (1 micro lot) = $0.2 risk per point
            micro_lots = risk_per_position / (sl_distance * 0.05)
            lot_size = micro_lots / 100
            logger.info(
                f"NAS100 calculation: ${risk_per_position} / ({sl_distance} * 0.2) = {micro_lots} micro lots = {lot_size:.2f} lots")

        # For Forex pairs
        elif is_forex:
            if is_jpy_pair:
                # For JPY pairs, pip is 0.01
                pip_size = 0.01
            else:
                # For other pairs, pip is 0.0001
                pip_size = 0.0001

            # Convert SL to pips
            sl_pips = sl_distance / pip_size

            # FOREX CALCULATION:
            # 0.01 lot (1 micro lot) = $0.1 risk per pip for major pairs
            micro_lots = risk_per_position / (sl_pips * 0.1)
            lot_size = micro_lots / 100
            logger.info(
                f"FOREX calculation: ${risk_per_position} / ({sl_pips} pips * 0.1) = {micro_lots} micro lots = {lot_size:.2f} lots")

        # Default for other instruments
        else:
            # Conservative approach with scaling
            micro_lots = risk_per_position / sl_distance
            lot_size = micro_lots / 100
            logger.info(
                f"Default calculation: ${risk_per_position} / {sl_distance} = {micro_lots} micro lots = {lot_size:.2f} lots")

        # Apply reasonable limits and rounding
        lot_size = min(lot_size, 10.0)  # Cap at 10.0 lots for safety
        lot_size = max(lot_size, 0.01)  # Minimum 0.01 lots
        lot_size = round(lot_size, 2)  # Round to 2 decimal places

        logger.info(f"Final lot size per position: {lot_size}")

        # Same size for all take profits
        position_sizes = [lot_size] * num_positions

        logger.info(f"Final position sizes: {position_sizes}, Total risk: ${total_risk_amount:.2f}")
        return position_sizes, round(total_risk_amount)

    except Exception as e:
        logger.error(f"Error calculating position size: {e}", exc_info=True)
        # Safe fallback
        position_sizes = [0.01] * len(take_profits)
        est_risk = account_balance * 0.005  # 0.5% risk
        logger.warning(f"Using fallback position sizes due to error: {position_sizes}")
        return position_sizes, round(est_risk)
# Clear exchange rate cache
def clear_exchange_rate_cache():
    """Clear the exchange rate cache"""
    _exchange_rate_cache.clear()
    _exchange_rate_ttl.clear()
    get_exchange_rate.cache_clear()  # Clear lru_cache