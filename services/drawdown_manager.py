import json
import os
import threading
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
import config.risk_config as risk_config

# Set up logging
logger = logging.getLogger(__name__)

# Global variables
max_drawdown_balance = 0  # This is the minimum balance the account should not drop below
drawdown_limit_file = 'data/daily_drawdown.json'
starting_balance = 0  # Balance at the start of the trading day (total equity)
_drawdown_lock = threading.RLock()  # Lock for thread-safe operations


# Function to load drawdown data
def load_drawdown_data(selected_account):
    """
    Load drawdown data from file with improved error handling.
    If file doesn't exist or is corrupted, initialize it properly.
    Checks if last_reset is from a previous day and flags for reset if needed.

    IMPORTANT: Validates that the data belongs to the selected account.
    If switching accounts, reinitializes with the new account's data.

    Returns:
        bool: True if drawdown needs to be reset (from previous day), False otherwise
    """
    global max_drawdown_balance, starting_balance

    needs_reset = False

    with _drawdown_lock:
        try:
            account_id = str(selected_account['id'])
            account_num = selected_account['accNum']

            if os.path.exists(drawdown_limit_file):
                with open(drawdown_limit_file, 'r') as file:
                    data = json.load(file)

                    # Check if the data belongs to the currently selected account
                    stored_account_id = data.get('account_id')

                    # If account_id is missing (old format) OR doesn't match, reinitialize
                    if not stored_account_id or stored_account_id != account_id:
                        if not stored_account_id:
                            logger.info(f"🔄 Setting up drawdown for Account #{account_num}...")
                        else:
                            logger.info(f"🔄 Switching to Account #{account_num}...")

                        # Initialize with new account's data
                        account_balance = float(selected_account['accountBalance'])
                        tier_size, _ = get_tier_size(account_balance)
                        # Get account-specific drawdown percentage
                        drawdown_percentage = risk_config.get_drawdown_percentage(account_id=account_num)

                        starting_balance = account_balance
                        drawdown_limit = tier_size * (drawdown_percentage / 100.0)
                        max_drawdown_balance = starting_balance - drawdown_limit

                        # Save with the new account_id (silent)
                        save_drawdown_data(selected_account)
                        needs_reset = True
                    else:
                        # Data belongs to the correct account, load it
                        max_drawdown_balance = data.get('max_drawdown_balance', 0)
                        starting_balance = data.get('starting_balance', 0)

                        # Check if last_reset was from a previous day
                        last_reset_str = data.get('last_reset')
                        if last_reset_str:
                            try:
                                # Parse the last reset timestamp
                                last_reset = datetime.fromisoformat(last_reset_str)
                                now = datetime.now(pytz.timezone('US/Eastern'))

                                # Check if last reset was on a different day
                                if last_reset.date() < now.date():
                                    logger.info(f"⏰ Last reset was on {last_reset.strftime('%Y-%m-%d')} - reset needed for today")
                                    needs_reset = True
                            except (ValueError, AttributeError) as e:
                                logger.warning(f"Could not parse last_reset date: {e}")
                                needs_reset = True

                        # Validate that we have valid data
                        if starting_balance <= 0 or max_drawdown_balance <= 0:
                            # Silent validation - will be fixed by validate_and_fix_drawdown
                            needs_reset = True

            else:
                logger.info("🔄 Initializing drawdown tracking...")

                # Set safe temporary values (very conservative)
                if selected_account:
                    account_balance = float(selected_account['accountBalance'])
                    tier_size, _ = get_tier_size(account_balance)
                    # Get account-specific drawdown percentage
                    account_num = selected_account.get('accNum')
                    drawdown_percentage = risk_config.get_drawdown_percentage(account_id=account_num)

                    # Use current balance as starting point temporarily
                    starting_balance = account_balance
                    drawdown_limit = tier_size * (drawdown_percentage / 100.0)
                    max_drawdown_balance = starting_balance - drawdown_limit

                    # Save the temporary values with account_id (silent)
                    save_drawdown_data(selected_account)
                    needs_reset = True

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in drawdown file: {e}")
            logger.info("Corrupted file will be fixed by validation")
            needs_reset = True
        except Exception as e:
            logger.error(f"Error loading drawdown data: {e}")
            needs_reset = True

    return needs_reset


# Function to save drawdown data
def save_drawdown_data(selected_account=None):
    """
    Save drawdown data to file with error handling.

    Args:
        selected_account: Optional account dict to save account_id
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

            # Prepare data to save
            data = {
                'max_drawdown_balance': max_drawdown_balance,
                'starting_balance': starting_balance,
                'last_reset': datetime.now(pytz.timezone('US/Eastern')).isoformat()
            }

            # Add account_id if provided to track which account this data belongs to
            if selected_account:
                data['account_id'] = str(selected_account['id'])
                data['account_num'] = selected_account['accNum']

            # Save new data
            with open(drawdown_limit_file, 'w') as file:
                json.dump(data, file, indent=2)

            logger.debug(f"Saved drawdown data: max_drawdown={max_drawdown_balance}, starting={starting_balance}")

        except Exception as e:
            logger.error(f"Error saving drawdown data: {e}")


# Function to determine the correct tier size based on account balance
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


# Enhanced reset daily drawdown function
async def reset_daily_drawdown_async(accounts_client, selected_account):
    """
    Reset daily drawdown based on current account state including unrealized P/L.

    Args:
        accounts_client: TradeLocker accounts client for API calls
        selected_account: Selected account information dictionary
    """
    global max_drawdown_balance, starting_balance

    with _drawdown_lock:
        try:
            # If accounts_client is None, use account balance from selected_account
            if accounts_client is None:
                account_balance = float(selected_account['accountBalance'])
                unrealized_pnl = 0  # Default to 0 without API access
                total_equity = account_balance
                logger.info("Using account balance without API access for drawdown calculation")
            else:
                # Get account state from API
                account_id = int(selected_account['id'])
                acc_num = int(selected_account['accNum'])

                account_state = await accounts_client.get_account_state_async(account_id, acc_num)

                if not account_state or 'd' not in account_state or 'accountDetailsData' not in account_state['d']:
                    logger.error("Failed to get account state data. Using account balance instead.")
                    account_balance = float(selected_account['accountBalance'])
                    unrealized_pnl = 0
                    total_equity = account_balance
                else:
                    # Extract data from account state response
                    details = account_state['d']['accountDetailsData']

                    # Access the fields using indices based on the API response format
                    account_balance = float(details[0])  # Balance (index 0) - Current realized balance
                    unrealized_pnl = float(details[23])  # Open Net P&L (index 23) - Unrealized profit/loss

                    # Calculate total equity (realized + unrealized)
                    total_equity = account_balance + unrealized_pnl

                    logger.info(
                        f"API data retrieved successfully: Balance={account_balance}, Unrealized P&L={unrealized_pnl}")

            # Determine the correct tier size based on realized balance
            tier_size, upper_limit = get_tier_size(account_balance)

            # Get the configurable drawdown percentage from risk config (account-specific)
            account_num = selected_account.get('accNum')
            drawdown_percentage = risk_config.get_drawdown_percentage(account_id=account_num)

            # Convert percentage to decimal for calculation (e.g., 4.0% -> 0.04)
            drawdown_decimal = drawdown_percentage / 100.0

            # Calculate drawdown limit using the configurable percentage
            drawdown_limit = tier_size * drawdown_decimal

            # Set starting balance (total equity) and max drawdown balance
            starting_balance = total_equity
            max_drawdown_balance = starting_balance - drawdown_limit

            logger.info(
                f"Daily drawdown limits for today: Account Balance=${account_balance:.2f}, "
                f"Tier=${tier_size}, Drawdown={drawdown_percentage:.1f}%, Drawdown Limit=${drawdown_limit:.2f}, "
                f"Max Drawdown Balance=${max_drawdown_balance:.2f}"
            )

            save_drawdown_data(selected_account)
            return True
        except Exception as e:
            logger.error(f"Error resetting daily drawdown: {e}", exc_info=True)
            return False


async def validate_and_fix_drawdown(accounts_client, selected_account):
    """
    Validates the current drawdown settings and fixes them ONLY if they're incorrect.
    Does NOT reset the drawdown on every restart - only fixes miscalculated values.

    The daily drawdown should only reset at the scheduled time (7 PM EST),
    not every time the bot restarts.

    Args:
        accounts_client: TradeLocker accounts client
        selected_account: Selected account info

    Returns:
        bool: True if validation passed or was fixed, False if error
    """
    global max_drawdown_balance

    try:
        # Get current account balance
        current_balance = float(selected_account['accountBalance'])

        # Get configured drawdown percentage from risk_config (account-specific)
        account_num = selected_account.get('accNum')
        drawdown_percentage = risk_config.get_drawdown_percentage(account_id=account_num)

        # Load current values from file
        with _drawdown_lock:
            file_max_dd = max_drawdown_balance
            file_starting = starting_balance

        # Determine tier size based on STARTING balance (not current)
        tier_size, _ = get_tier_size(file_starting)

        # Calculate what the max_drawdown_balance SHOULD be based on starting balance
        correct_drawdown_limit = tier_size * (drawdown_percentage / 100.0)
        correct_max_drawdown = file_starting - correct_drawdown_limit

        # Calculate current daily loss/gain
        daily_pnl = current_balance - file_starting

        # Check if the saved max_drawdown_balance is correct
        needs_correction = False

        # Calculate what percentage the file actually represents
        if file_starting > 0 and tier_size > 0:
            file_drawdown_amount = file_starting - file_max_dd
            file_drawdown_percentage = (file_drawdown_amount / tier_size) * 100

            # Check if percentage is wrong (tolerance of 0.1%)
            if abs(file_drawdown_percentage - drawdown_percentage) > 0.1:
                needs_correction = True
        else:
            needs_correction = True

        # Apply correction ONLY if the calculation is wrong
        if needs_correction:
            logger.info("🔧 Correcting drawdown calculation...")

            with _drawdown_lock:
                max_drawdown_balance = correct_max_drawdown

            save_drawdown_data(selected_account)

        # Display trader-friendly summary
        logger.info("")
        logger.info("💼 ═══════════════════════════════════════════════════════════")
        logger.info(f"   DAILY RISK LIMITS - Account #{selected_account['accNum']}")
        logger.info("   ═══════════════════════════════════════════════════════════")
        logger.info(f"   💰 Current Balance:    ${current_balance:,.2f}")
        logger.info(f"   📊 Starting Balance:   ${file_starting:,.2f}")
        logger.info(f"   🎯 Tier Size:          ${tier_size:,.2f}")
        logger.info(f"   🛡️  Max Loss Allowed:   ${correct_drawdown_limit:,.2f} ({drawdown_percentage}%)")
        logger.info("")

        # Show P&L status
        if daily_pnl >= 0:
            logger.info(f"   📈 Daily P&L:          +${daily_pnl:,.2f} ✨")
        else:
            remaining = current_balance - file_max_dd
            logger.info(f"   📉 Daily P&L:          ${daily_pnl:,.2f}")
            logger.info(f"   💵 Room to Trade:      ${remaining:,.2f}")

            # Check status
            if current_balance <= file_max_dd:
                logger.info("")
                logger.info("   🚨 TRADING HALTED - Daily limit reached!")
            elif remaining < correct_drawdown_limit * 0.2:  # Within 20% of limit
                logger.info("   ⚠️  Approaching limit - Trade carefully!")

        logger.info("   ═══════════════════════════════════════════════════════════")
        logger.info("")

        return True

    except Exception as e:
        logger.error(f"❌ Error validating drawdown: {e}")
        return False

# Synchronous wrapper for reset_daily_drawdown


def reset_daily_drawdown(accounts_client, selected_account):
    """
    Synchronous wrapper for reset_daily_drawdown_async.

    Args:
        accounts_client: TradeLocker accounts client for API calls
        selected_account: Selected account information dictionary
    """
    global max_drawdown_balance, starting_balance

    try:
        # Check if we're in an event loop
        try:
            loop = asyncio.get_event_loop()
            in_event_loop = loop.is_running()
        except RuntimeError:
            in_event_loop = False

        if in_event_loop:
            # If we're already in a running event loop, we can't use run_until_complete
            # Instead, set the drawdown values based on account balance without API
            with _drawdown_lock:
                account_balance = float(selected_account['accountBalance'])
                tier_size, _ = get_tier_size(account_balance)

                # Get the configurable drawdown percentage (account-specific)
                account_num = selected_account.get('accNum')
                drawdown_percentage = risk_config.get_drawdown_percentage(account_id=account_num)
                drawdown_decimal = drawdown_percentage / 100.0

                # Calculate using configurable percentage
                drawdown_limit = tier_size * drawdown_decimal

                starting_balance = account_balance
                max_drawdown_balance = starting_balance - drawdown_limit

                logger.info(
                    f"Balance=${account_balance:.2f}, Tier=${tier_size}, "
                    f"Drawdown={drawdown_percentage:.1f}%, "
                    f"Drawdown Limit=${drawdown_limit:.2f}, "
                    f"Max Drawdown Balance=${max_drawdown_balance:.2f}"
                )

                save_drawdown_data(selected_account)
                return True
        else:
            # No event loop running, we can create one and run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(reset_daily_drawdown_async(accounts_client, selected_account))

    except Exception as e:
        logger.error(f"Error in synchronous reset_daily_drawdown: {e}", exc_info=True)

        # Fallback to simple calculation without API
        with _drawdown_lock:
            account_balance = float(selected_account['accountBalance'])
            tier_size, _ = get_tier_size(account_balance)

            # Get the configurable drawdown percentage even in fallback (account-specific)
            account_num = selected_account.get('accNum')
            drawdown_percentage = risk_config.get_drawdown_percentage(account_id=account_num)
            drawdown_decimal = drawdown_percentage / 100.0

            # Calculate using configurable percentage
            drawdown_limit = tier_size * drawdown_decimal

            starting_balance = account_balance
            max_drawdown_balance = starting_balance - drawdown_limit

            logger.info(
                f"Daily drawdown reset (fallback): Balance=${account_balance:.2f}, "
                f"Tier=${tier_size}, Drawdown={drawdown_percentage:.1f}%, "
                f"Drawdown Limit=${drawdown_limit:.2f}, "
                f"Max Drawdown Balance=${max_drawdown_balance:.2f}"
            )

            save_drawdown_data(selected_account)
            return False


async def schedule_daily_reset_async(accounts_client, selected_account):
    """
    Schedule daily reset using asyncio instead of threading
    """
    try:
        # Get current time in EST timezone
        now = datetime.now(pytz.timezone('America/New_York'))

        # Set reset time to 7:00 PM EST
        reset_time = now.replace(hour=19, minute=0, second=0, microsecond=0)

        # If current time is past 7 PM, schedule for next day
        if now >= reset_time:
            reset_time += timedelta(days=1)

        # Calculate wait time in seconds
        wait_time = (reset_time - now).total_seconds()

        logger.info(f"⏰ Next reset at {reset_time.strftime('%I:%M %p')} EST ({reset_time.strftime('%b %d')})")

        # Sleep until it's time to reset
        await asyncio.sleep(wait_time)

        # Perform the reset directly with the async function
        logger.info("")
        logger.info("🔄 ═══════════════════════════════════════════════════════════")
        logger.info("   DAILY RESET - Refreshing drawdown limits...")
        logger.info("   ═══════════════════════════════════════════════════════════")
        await reset_daily_drawdown_async(accounts_client, selected_account)
        logger.info("   ✅ Reset complete - Fresh limits applied!")
        logger.info("   ═══════════════════════════════════════════════════════════")
        logger.info("")

        # Schedule the next reset
        asyncio.create_task(schedule_daily_reset_async(accounts_client, selected_account))

    except asyncio.CancelledError:
        logger.info("Drawdown reset task was cancelled")
    except Exception as e:
        logger.error(f"Error scheduling daily reset: {e}")
        # Fallback: Try again in 1 hour
        await asyncio.sleep(3600)
        asyncio.create_task(schedule_daily_reset_async(accounts_client, selected_account))


# Function to perform the scheduled reset
def perform_daily_reset(accounts_client, selected_account):
    """
    Perform the daily reset and schedule the next one.

    Args:
        accounts_client: TradeLocker accounts client for API calls
        selected_account: Selected account information dictionary
    """
    try:
        logger.info("Performing scheduled daily drawdown reset")
        reset_daily_drawdown(accounts_client, selected_account)
        # Schedule the next reset
        schedule_daily_reset_async(accounts_client, selected_account)
    except Exception as e:
        logger.error(f"Error in daily reset: {e}")
        # Fallback: Try again in 1 hour
        threading.Timer(3600, schedule_daily_reset_async, args=[accounts_client, selected_account]).start()


# Async version of reset for use in async contexts
async def reset_daily_drawdown_async_wrapper(accounts_client, selected_account):
    """
    Asynchronous wrapper for reset_daily_drawdown.

    Args:
        accounts_client: TradeLocker accounts client for API calls
        selected_account: Selected account information dictionary
    """
    return await reset_daily_drawdown_async(accounts_client, selected_account)


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
                "Max drawdown balance: {max_drawdown_balance}"
            )

        return exceed
