import json
import os
import threading
import asyncio
import logging
from datetime import datetime, timedelta
import pytz

# Set up logging
logger = logging.getLogger(__name__)

# Global variables
max_drawdown_balance = 0  # This is the minimum balance the account should not drop below
drawdown_limit_file = '../daily_drawdown.json'
starting_balance = 0  # Balance at the start of the trading day
_drawdown_lock = threading.RLock()  # Lock for thread-safe operations


# Function to load drawdown data
def load_drawdown_data(selected_account):
    """
    Load drawdown data from file with improved error handling.
    """
    global max_drawdown_balance, starting_balance

    with _drawdown_lock:
        try:
            if os.path.exists(drawdown_limit_file):
                with open(drawdown_limit_file, 'r') as file:
                    data = json.load(file)
                    max_drawdown_balance = data.get('max_drawdown_balance', 0)
                    starting_balance = data.get('starting_balance', 0)

                    logger.info(
                        f"Loaded drawdown data: max_drawdown={max_drawdown_balance}, starting={starting_balance}")
            else:
                logger.info("No existing drawdown file. Creating new limits.")
                reset_daily_drawdown(selected_account)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in drawdown file: {e}")
            logger.info("Creating new drawdown limits due to corrupted file.")
            reset_daily_drawdown(selected_account)
        except Exception as e:
            logger.error(f"Error loading drawdown data: {e}")
            # Set safe defaults if we can't load
            if selected_account:
                account_balance = float(selected_account['accountBalance'])
                max_drawdown_balance = account_balance * 0.96  # Default to 4% max drawdown
                starting_balance = account_balance


# Function to save drawdown data
def save_drawdown_data():
    """
    Save drawdown data to file with error handling.
    """
    with _drawdown_lock:
        try:
            # Create backup of existing file if it exists
            if os.path.exists(drawdown_limit_file):
                backup_file = f"{drawdown_limit_file}.bak"
                try:
                    with open(drawdown_limit_file, 'r') as src:
                        with open(backup_file, 'w') as dst:
                            dst.write(src.read())
                except Exception as e:
                    logger.warning(f"Could not create backup of drawdown file: {e}")

            # Save new data
            with open(drawdown_limit_file, 'w') as file:
                json.dump({
                    'max_drawdown_balance': max_drawdown_balance,
                    'starting_balance': starting_balance
                }, file, indent=2)

            logger.debug(f"Saved drawdown data: max_drawdown={max_drawdown_balance}, starting={starting_balance}")

        except Exception as e:
            logger.error(f"Error saving drawdown data: {e}")


# Function to determine the correct tier size and apply the 10% rule
def get_tier_size(account_balance):
    """
    Determine correct tier size based on account balance.
    Returns tuple of (tier_size, max_balance)
    """
    if account_balance <= 9000:
        return 5000, 9000  # $5,000 tier, max balance is $9,000
    elif account_balance <= 22500:
        return 10000, 22500  # $10,000 tier, max balance is $22,500
    elif account_balance <= 45000:
        return 25000, 45000  # $25,000 tier, max balance is $45,000
    elif account_balance <= 90000:
        return 50000, 90000  # $50,000 tier, max balance is $90,000
    else:
        return 100000, float('inf')  # $100,000 tier, no upper limit


# Function to reset the daily drawdown
def reset_daily_drawdown(selected_account):
    """
    Reset daily drawdown based on current account balance.
    """
    global max_drawdown_balance, starting_balance

    with _drawdown_lock:
        try:
            # Get the latest balance
            account_balance = float(selected_account['accountBalance'])

            # Determine the correct tier size and its upper limit
            tier_size, upper_limit = get_tier_size(account_balance)

            # The drawdown is based on the tier, so calculate 4% of the tier size
            drawdown_limit = tier_size * 0.04

            # Set the starting balance and max drawdown balance
            starting_balance = account_balance
            max_drawdown_balance = starting_balance - drawdown_limit

            logger.info(
                f"Daily drawdown limit set. Starting balance: {starting_balance}, "
                f"Max drawdown balance: {max_drawdown_balance} based on tier {tier_size}"
            )
            save_drawdown_data()

        except Exception as e:
            logger.error(f"Error resetting daily drawdown: {e}")


# Function to schedule the daily drawdown reset
def schedule_daily_reset(selected_account):
    """
    Schedule a daily reset of drawdown limits at 6 PM EST.
    """
    try:
        now = datetime.now(pytz.timezone('America/New_York'))
        reset_time = now.replace(hour=18, minute=0, second=0, microsecond=0)

        if now >= reset_time:
            reset_time += timedelta(days=1)

        wait_time = (reset_time - now).total_seconds()

        logger.info(f"Scheduling next drawdown reset at {reset_time.strftime('%Y-%m-%d %H:%M:%S')} EST")
        threading.Timer(wait_time, perform_daily_reset, args=[selected_account]).start()

    except Exception as e:
        logger.error(f"Error scheduling daily reset: {e}")
        # Fallback: Try again in 1 hour
        threading.Timer(3600, schedule_daily_reset, args=[selected_account]).start()


def perform_daily_reset(selected_account):
    """
    Perform the daily reset and schedule the next one.
    """
    try:
        logger.info("Performing scheduled daily drawdown reset")
        reset_daily_drawdown(selected_account)
        schedule_daily_reset(selected_account)
    except Exception as e:
        logger.error(f"Error in daily reset: {e}")
        # Fallback: Try again in 1 hour
        threading.Timer(3600, schedule_daily_reset, args=[selected_account]).start()


# Async version of reset for use in async contexts
async def reset_daily_drawdown_async(selected_account):
    """
    Asynchronous wrapper for reset_daily_drawdown.
    """
    # Use run_in_executor to run the synchronous function in a thread pool
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, reset_daily_drawdown, selected_account)


# Check if an operation would exceed drawdown limits
def would_exceed_drawdown(account_balance, risk_amount):
    """
    Check if a trade with the given risk would exceed drawdown limits.

    Args:
        account_balance: Current account balance
        risk_amount: Amount at risk for the trade

    Returns:
        bool: True if drawdown would be exceeded, False otherwise
    """
    with _drawdown_lock:
        projected_balance = account_balance - risk_amount
        exceed = projected_balance < max_drawdown_balance

        if exceed:
            logger.warning(
                f"Trade would exceed drawdown limits. Current balance: {account_balance}, "
                f"Risk amount: {risk_amount}, Projected balance: {projected_balance}, "
                f"Max drawdown balance: {max_drawdown_balance}"
            )

        return exceed