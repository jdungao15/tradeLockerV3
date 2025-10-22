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
drawdown_file = 'data/accounts_drawdown.json'
_drawdown_lock = threading.RLock()
_accounts_drawdown_cache = {}  # In-memory cache of all account drawdowns


# ============================================================================
# DATA STRUCTURE MANAGEMENT
# ============================================================================

def load_accounts_drawdown():
    """
    Load all accounts' drawdown data from file.
    Returns dict with account_id as key.
    """

    with _drawdown_lock:
        try:
            if os.path.exists(drawdown_file):
                with open(drawdown_file, 'r') as file:
                    data = json.load(file)
                    _accounts_drawdown_cache = data.get('accounts', {})
                    # Silent load - no logging for trader UI
            else:
                _accounts_drawdown_cache = {}

        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in drawdown file: {e}")
            _accounts_drawdown_cache = {}
        except Exception as e:
            logger.error(f"❌ Error loading accounts drawdown data: {e}")
            _accounts_drawdown_cache = {}

    return _accounts_drawdown_cache


def save_accounts_drawdown():
    """Save all accounts' drawdown data to file."""

    with _drawdown_lock:
        try:
            # Create backup if file exists
            if os.path.exists(drawdown_file):
                backup_file = f"{drawdown_file}.bak"
                try:
                    with open(drawdown_file, 'r') as src:
                        with open(backup_file, 'w') as dst:
                            dst.write(src.read())
                except Exception as e:
                    logger.warning(f"Could not create backup: {e}")

            # Save current data
            data = {
                'accounts': _accounts_drawdown_cache,
                'last_updated': datetime.now(pytz.timezone('US/Eastern')).isoformat()
            }

            with open(drawdown_file, 'w') as file:
                json.dump(data, file, indent=2)

            logger.debug(f"Saved drawdown data for {len(_accounts_drawdown_cache)} accounts")
            return True

        except Exception as e:
            logger.error(f"Error saving accounts drawdown data: {e}")
            return False


# ============================================================================
# TIER CALCULATION
# ============================================================================

def get_tier_size(account_balance):
    """
    Determine correct tier size based on account balance.
    Uses 90% of tier size as threshold to account for losses/drawdown.

    For prop firm accounts, the tier represents your account size,
    not your current balance. Thresholds are set at 90% to properly
    identify the account tier even after some losses.

    Returns:
        tuple: (tier_size, tier_name)
    """
    if account_balance >= 180000:  # 90% of 200k
        return 200000, "200k"
    elif account_balance >= 90000:  # 90% of 100k
        return 100000, "100k"
    elif account_balance >= 45000:  # 90% of 50k ← FIXED
        return 50000, "50k"
    elif account_balance >= 22500:  # 90% of 25k ← FIXED
        return 25000, "25k"
    elif account_balance >= 9000:  # 90% of 10k ← FIXED
        return 10000, "10k"
    elif account_balance >= 4500:  # 90% of 5k ← FIXED
        return 5000, "5k"
    else:
        return account_balance, "custom"


# ============================================================================
# SINGLE ACCOUNT OPERATIONS
# ============================================================================

def get_account_drawdown(account_id):
    """
    Get drawdown data for a specific account.

    Args:
        account_id: Account ID (string)

    Returns:
        dict: Account drawdown data or None if not found
    """

    with _drawdown_lock:
        return _accounts_drawdown_cache.get(str(account_id))


def get_max_drawdown_balance(account_id):
    """
    Get the max drawdown balance for a specific account.

    Args:
        account_id: Account ID (string)

    Returns:
        float: Max drawdown balance or 0 if not set
    """
    account_data = get_account_drawdown(str(account_id))
    if account_data:
        return float(account_data.get('max_drawdown_balance', 0))
    return 0


def initialize_account_drawdown(account):
    """
    Initialize drawdown tracking for a new account or reset existing one.

    Args:
        account: Account dict from API (with 'id', 'accNum', 'accountBalance', 'status')

    Returns:
        bool: Success status
    """

    try:
        account_id = str(account['id'])
        account_balance = float(account['accountBalance'])

        # Only initialize ACTIVE accounts
        if account.get('status') != 'ACTIVE':
            return False

        # Calculate drawdown values
        tier_size, tier_name = get_tier_size(account_balance)
        drawdown_percentage = risk_config.get_drawdown_percentage()
        drawdown_limit = tier_size * (drawdown_percentage / 100.0)
        max_drawdown_balance = account_balance - drawdown_limit

        with _drawdown_lock:
            _accounts_drawdown_cache[account_id] = {
                'account_id': account_id,
                'accNum': account['accNum'],
                'starting_balance': account_balance,
                'max_drawdown_balance': max_drawdown_balance,
                'tier_size': tier_size,
                'tier_name': tier_name,
                'drawdown_percentage': drawdown_percentage,
                'drawdown_limit': drawdown_limit,
                'last_reset': datetime.now(pytz.timezone('US/Eastern')).isoformat(),
                'status': account['status']
            }

            save_accounts_drawdown()

        # Silent initialization for trader UI

        return True

    except Exception as e:
        logger.error(f"❌ Error initializing account drawdown: {e}")
        return False


def would_exceed_drawdown(account_id, current_balance, risk_amount):
    """
    Check if a trade would exceed drawdown limits for a specific account.

    Args:
        account_id: Account ID (string)
        current_balance: Current account balance
        risk_amount: Amount at risk for the trade

    Returns:
        bool: True if drawdown would be exceeded, False otherwise
    """
    account_data = get_account_drawdown(str(account_id))

    if not account_data:
        logger.warning(f"No drawdown data for account {account_id}. Allowing trade (unsafe!).")
        return False

    max_dd = float(account_data.get('max_drawdown_balance', 0))
    projected_balance = current_balance - risk_amount
    exceed = projected_balance < max_dd

    if exceed:
        logger.warning(
            f"Account {account_id}: Trade would exceed drawdown. "
            f"Current=${current_balance:,.2f}, Risk=${risk_amount:,.2f}, "
            f"Projected=${projected_balance:,.2f}, Limit=${max_dd:,.2f}"
        )

    return exceed


# ============================================================================
# MULTI-ACCOUNT OPERATIONS
# ============================================================================

async def sync_all_accounts_from_api(accounts_client):
    """
    Fetch all accounts from API and initialize/update drawdown tracking.
    Only processes ACTIVE accounts.

    Args:
        accounts_client: TradeLocker accounts client

    Returns:
        list: List of active accounts with drawdown tracking
    """
    try:
        # Fetch all accounts from API
        response = await accounts_client.get_accounts_async()

        if not response or 'accounts' not in response:
            logger.error("Failed to fetch accounts from API")
            return []

        accounts_list = response['accounts']
        active_accounts = []

        logger.info("=" * 70)
        logger.info("SYNCING ACCOUNTS WITH DRAWDOWN MANAGER")
        logger.info("=" * 70)

        for account in accounts_list:
            account_id = str(account['id'])
            status = account.get('status', 'UNKNOWN')

            logger.info(f"\nAccount {account_id} (#{account['accNum']}): Status={status}")

            if status == 'ACTIVE':
                # Initialize or update this account's drawdown
                if initialize_account_drawdown(account):
                    active_accounts.append(account)
                    logger.info("  ✓ Drawdown tracking enabled")
            else:
                logger.info("  ⊘ Skipped (not ACTIVE)")

        logger.info("=" * 70)
        logger.info(f"Total accounts tracked: {len(active_accounts)}")
        logger.info("=" * 70)

        return active_accounts

    except Exception as e:
        logger.error(f"Error syncing accounts: {e}", exc_info=True)
        return []


async def reset_all_accounts_drawdown_async(accounts_client):
    """
    Reset daily drawdown for monitored accounts only (not all accounts).
    Called at scheduled reset time (7 PM EST).

    Args:
        accounts_client: TradeLocker accounts client

    Returns:
        bool: Success status
    """

    try:
        # Get list of currently monitored accounts from cache
        monitored_account_ids = list(_accounts_drawdown_cache.keys())

        if not monitored_account_ids:
            return False

        # Fetch all accounts from API to get updated balances
        response = await accounts_client.get_accounts_async()

        if not response or 'accounts' not in response:
            logger.error("   ❌ Could not fetch account data from API")
            return False

        accounts_list = response['accounts']
        reset_count = 0

        # Reset only the accounts that are in our monitored list
        for account in accounts_list:
            account_id = str(account['id'])

            # Only process accounts that are being monitored
            if account_id in monitored_account_ids:
                status = account.get('status', 'UNKNOWN')

                if status == 'ACTIVE':
                    # Reset this account's drawdown
                    if initialize_account_drawdown(account):
                        reset_count += 1
                        logger.info(f"   ✅ Account #{account['accNum']} reset")

        logger.info(f"   📊 {reset_count} account(s) refreshed")

        return reset_count > 0

    except Exception as e:
        logger.error(f"   ❌ Error resetting accounts: {e}")
        return False


# ============================================================================
# SCHEDULED RESET
# ============================================================================

async def schedule_daily_reset_async(accounts_client):
    """
    Schedule daily drawdown reset at 7 PM EST for all accounts.

    Args:
        accounts_client: TradeLocker accounts client
    """
    est = pytz.timezone('US/Eastern')

    # Silent initialization

    while True:
        try:
            now = datetime.now(est)

            # Calculate next reset time (7 PM EST today or tomorrow)
            reset_time = now.replace(hour=19, minute=0, second=0, microsecond=0)

            if now >= reset_time:
                # If past 7 PM, schedule for tomorrow
                reset_time += timedelta(days=1)

            wait_seconds = (reset_time - now).total_seconds()

            # Wait until reset time (silent)
            await asyncio.sleep(wait_seconds)

            # Perform reset for all accounts
            logger.info("")
            logger.info("🔄 ═══════════════════════════════════════════════════════════")
            logger.info("   MULTI-ACCOUNT DAILY RESET")
            logger.info("   ═══════════════════════════════════════════════════════════")
            success = await reset_all_accounts_drawdown_async(accounts_client)

            if success:
                logger.info("   ✅ All accounts reset successfully!")
            else:
                logger.info("   ⚠️  Some accounts could not be reset")

            logger.info("   ═══════════════════════════════════════════════════════════")
            logger.info("")

            # Wait a bit to avoid immediate re-trigger
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"❌ Error in daily reset scheduler: {e}")
            await asyncio.sleep(300)  # Wait 5 minutes before retry


# ============================================================================
# VALIDATION & DIAGNOSTICS
# ============================================================================

async def validate_account_drawdown(accounts_client, account):
    """
    Validate drawdown settings for a specific account.

    Args:
        accounts_client: TradeLocker accounts client
        account: Account dict with 'id', 'accountBalance', etc.

    Returns:
        bool: True if valid or fixed, False if error
    """
    try:
        account_id = str(account['id'])
        current_balance = float(account['accountBalance'])

        logger.info("=" * 60)
        logger.info(f"VALIDATING DRAWDOWN FOR ACCOUNT {account_id}")
        logger.info("=" * 60)

        # Get stored drawdown data
        account_data = get_account_drawdown(account_id)

        if not account_data:
            logger.warning(f"No drawdown data found for account {account_id}")
            logger.info("Initializing drawdown tracking...")
            initialize_account_drawdown(account)
            return True

        # Display current settings
        logger.info(f"Current Balance: ${current_balance:,.2f}")
        logger.info(f"Starting Balance: ${account_data.get('starting_balance', 0):,.2f}")
        logger.info(f"Max Drawdown Balance: ${account_data.get('max_drawdown_balance', 0):,.2f}")
        logger.info(f"Tier: {account_data.get('tier_name')} (${account_data.get('tier_size', 0):,.2f})")
        logger.info(f"Drawdown %: {account_data.get('drawdown_percentage', 0):.1f}%")

        # Calculate P&L
        starting = float(account_data.get('starting_balance', 0))
        max_dd = float(account_data.get('max_drawdown_balance', 0))

        daily_pnl = current_balance - starting
        remaining = current_balance - max_dd

        if daily_pnl >= 0:
            logger.info(f"📈 Daily P&L: +${daily_pnl:,.2f} (profit)")
        else:
            logger.info(f"📉 Daily P&L: ${daily_pnl:,.2f} (loss)")

        logger.info(f"💰 Remaining before limit: ${remaining:,.2f}")

        # Check if limit would be exceeded
        if current_balance < max_dd:
            logger.error("⚠️ DRAWDOWN LIMIT REACHED! Trading should be stopped.")

        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.error(f"Error validating account drawdown: {e}", exc_info=True)
        return False


def display_all_accounts_drawdown():
    """Display drawdown status for all tracked accounts."""

    if not _accounts_drawdown_cache:
        return

    logger.info("")
    logger.info("📊 ════════════════════════════════════════════════════════════════")
    logger.info("   MULTI-ACCOUNT MONITORING")
    logger.info("   ════════════════════════════════════════════════════════════════")

    for account_id, data in _accounts_drawdown_cache.items():
        tier_name = data.get('tier_name', 'Unknown')
        drawdown_pct = data.get('drawdown_percentage', 0)
        starting = data.get('starting_balance', 0)
        status = data.get('status', 'UNKNOWN')

        status_emoji = "✅" if status == "ACTIVE" else "⏸️"

        logger.info(
            f"   {status_emoji} Account #{data.get('accNum')} | {tier_name} Tier | ${starting:,.2f} | {drawdown_pct:.1f}% limit")

    logger.info("   ════════════════════════════════════════════════════════════════")
    logger.info("   🔄 All accounts reset daily at 7:00 PM EST")
    logger.info("   ════════════════════════════════════════════════════════════════")
    logger.info("")


# ============================================================================
# INITIALIZATION
# ============================================================================

# Load accounts data on module import
load_accounts_drawdown()
