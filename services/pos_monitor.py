import asyncio
import aiohttp
import logging
import time
from typing import Dict, List, Any

logger = logging.getLogger(__name__)
def calculate_pip_difference(entry_price, current_price, instrument_name):
    """
    Calculate pip difference based on the instrument type.
    """
    if instrument_name.endswith("JPY"):
        return round(abs(current_price - entry_price) / 0.01)
    elif instrument_name == "XAUUSD":  # For Gold
        return round(abs(current_price - entry_price) / 0.1)
    elif instrument_name in ["DJI30", "NDX100"]:  # For indices
        return round(abs(current_price - entry_price) / 1.0)
    else:
        return round(abs(current_price - entry_price) / 0.0001)

async def monitor_existing_position(accounts_client, instruments_client, quotes_client,
                                    selected_account, base_url, auth_token):
    """
    Function to check and monitor any existing open positions asynchronously.
    """
    account_id = selected_account['id']
    acc_num = selected_account['accNum']

    # Local cache to avoid repeated lookups
    instrument_cache = {}
    position_tracking = {}  # Track position updates to avoid redundant API calls

    logger.info("Starting position monitoring service")

    while True:
        try:
            logger.debug("Checking for open positions...")

            # Get current positions
            positions = await accounts_client.get_current_position_async(account_id, acc_num)

            if positions and positions.get('d', {}).get('positions'):
                position_data_list = positions['d']['positions']

                # Process positions in parallel for efficiency
                await process_positions_parallel(
                    position_data_list,
                    instruments_client,
                    quotes_client,
                    selected_account,
                    base_url,
                    auth_token,
                    instrument_cache,
                    position_tracking
                )
            else:
                logger.debug("No open positions found")

        except Exception as e:
            logger.error(f"Error in position monitoring: {e}", exc_info=True)

        # Adaptive polling interval: check more frequently when positions exist
        if positions and positions.get('d', {}).get('positions'):
            await asyncio.sleep(3)  # 3 seconds when positions exist
        else:
            await asyncio.sleep(10)  # 10 seconds when no positions


async def process_positions_parallel(positions, instruments_client, quotes_client,
                                     selected_account, base_url, auth_token,
                                     instrument_cache, position_tracking):
    """
    Process multiple positions in parallel for better efficiency
    """
    tasks = []

    for position_data in positions:
        task = asyncio.create_task(
            monitor_single_position(
                position_data,
                instruments_client,
                quotes_client,
                selected_account,
                base_url,
                auth_token,
                instrument_cache,
                position_tracking
            )
        )
        tasks.append(task)

    # Wait for all position monitoring tasks to complete
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def monitor_single_position(position_data, instruments_client, quotes_client,
                                  selected_account, base_url, auth_token,
                                  instrument_cache, position_tracking):
    """
    Monitor a single position with improved caching and rate limiting
    """
    try:
        position_id = position_data[0]  # Position ID
        instrument_id = position_data[1]  # Instrument ID
        entry_price = float(position_data[5])  # Entry price
        side = position_data[3]  # Buy or Sell side ('buy' or 'sell')

        # Skip recently updated positions to avoid API rate limits
        current_time = time.time()
        last_update = position_tracking.get(position_id, {}).get('last_update', 0)
        if current_time - last_update < 30:  # 30 second cooldown between updates
            return

        # Check if instrument already in cache
        if instrument_id not in instrument_cache:
            instrument_data = await instruments_client.get_instrument_by_id_async(
                selected_account['id'],
                selected_account['accNum'],
                instrument_id
            )

            if not instrument_data:
                logger.warning(f"Instrument data for ID {instrument_id} not found")
                return

            instrument_cache[instrument_id] = instrument_data
        else:
            instrument_data = instrument_cache[instrument_id]

        instrument_name = instrument_data['name']

        # Get real-time quote
        real_time_quote = await quotes_client.get_quote_async(selected_account, instrument_name)

        if not real_time_quote or 'd' not in real_time_quote:
            logger.warning(f"Failed to get quote for {instrument_name}")
            return

        # Process the position with the current price
        await process_position_update(
            position_id,
            instrument_data,
            side,
            entry_price,
            real_time_quote,
            selected_account,
            base_url,
            auth_token,
            position_tracking
        )

    except Exception as e:
        logger.error(f"Error monitoring position {position_data[0]}: {e}", exc_info=True)


async def process_position_update(position_id, instrument_data, side, entry_price,
                                  quote_data, selected_account, base_url, auth_token,
                                  position_tracking):
    """
    Process position update with improved logic and tracking
    """
    try:
        instrument_name = instrument_data['name']
        instrument_type = instrument_data.get('type', '')
        ask_price = quote_data['d'].get('ap', 0)
        bid_price = quote_data['d'].get('bp', 0)

        # For a 'buy' position, the current price is the bid price (what you can sell for)
        # For a 'sell' position, the current price is the ask price (what you can buy for)
        current_price = bid_price if side.lower() == 'buy' else ask_price

        # Calculate pip difference
        pip_difference = calculate_pip_difference(entry_price, current_price, instrument_name)

        # Get current position tracking data
        tracking_data = position_tracking.get(position_id, {
            'last_update': 0,
            'stop_loss_moved': False,
            'pip_high': 0,
            'is_runner': False  # Flag to identify runner positions
        })

        # Store instrument name and position ID for future reference
        tracking_data['instrument_name'] = instrument_name
        tracking_data['position_id'] = position_id

        # Determine if this is a CFD runner position to apply selective trailing
        is_cfd = instrument_type == "EQUITY_CFD"
        is_gold = instrument_name == "XAUUSD"
        is_index = instrument_name in ["DJI30", "NDX100"]

        # CFD instruments (including gold) should have trailing, but with different rules
        should_trail = is_cfd

        # Additional check for runner position (third position)
        # If this is the first time we're processing this position
        if should_trail and 'is_runner_checked' not in tracking_data:
            # Mark as checked to avoid repeated checks
            tracking_data['is_runner_checked'] = True

            # For simplicity, we identify runners by their order ID or position in the batch
            # In production, you might want a more robust identification method
            # Here we're checking for positions whose ID ends with specific characters
            # or using other attributes that identify your "runner" positions

            # Check if this is the "runner" position - the third position for indices
            # You may need to customize this logic based on how your positions are created
            if position_id.endswith('3') or tracking_data.get('is_third_position', False):
                tracking_data['is_runner'] = True
                logger.info(f"Position {position_id} ({instrument_name}) identified as runner - will apply trailing")
            else:
                logger.info(f"Position {position_id} ({instrument_name}) is not a runner - won't apply trailing")

        # Check if this position should be trailed
        should_trail = should_trail and tracking_data.get('is_runner', False)

        # Track the highest pip movement in favor
        if side.lower() == 'buy' and current_price > entry_price:
            tracking_data['pip_high'] = max(tracking_data['pip_high'], pip_difference)
        elif side.lower() == 'sell' and current_price < entry_price:
            tracking_data['pip_high'] = max(tracking_data['pip_high'], pip_difference)

        # Determine if stop loss update is needed
        update_needed = False

        # Only apply trailing to identified runner positions with appropriate pip difference
        if should_trail:
            # Set threshold based on instrument type
            pip_threshold = 100 if is_index else 40  # 100 pips for indices, 40 pips for gold

            # If price has moved beyond threshold pips in favor and stop loss hasn't been moved yet
            if not tracking_data['stop_loss_moved'] and pip_difference >= pip_threshold:
                if (side.lower() == 'buy' and current_price > entry_price) or \
                        (side.lower() == 'sell' and current_price < entry_price):
                    update_needed = True
                    tracking_data['stop_loss_moved'] = True
                    logger.info(
                        f"Runner position {position_id} ({instrument_name}): Initiating trailing stop at {pip_difference} pips (threshold: {pip_threshold} pips)")

            # If price has moved significantly further after initial stop loss move
            # implement trailing stop logic with 20 pip pullback
            elif tracking_data['stop_loss_moved'] and tracking_data['pip_high'] - pip_difference >= 20:
                # Price has pulled back 20 pips from highest point, move stop loss again
                update_needed = True
                logger.info(
                    f"Runner position {position_id} ({instrument_name}): Trailing stop - {tracking_data['pip_high'] - pip_difference} pip pullback from highest")

        # For non-runner positions, apply the original logic (40 pip threshold)
        # This keeps the existing behavior for non-CFD instruments and gold
        elif not should_trail and not is_cfd:
            # If price has moved 40+ pips in favor and stop loss hasn't been moved yet
            if not tracking_data['stop_loss_moved'] and pip_difference >= 40:
                if (side.lower() == 'buy' and current_price > entry_price) or \
                        (side.lower() == 'sell' and current_price < entry_price):
                    update_needed = True
                    tracking_data['stop_loss_moved'] = True

            # If price has moved significantly further after initial stop loss move
            # implement trailing stop logic
            elif tracking_data['stop_loss_moved'] and tracking_data['pip_high'] - pip_difference >= 20:
                # Price has pulled back 20 pips from highest point, move stop loss again
                update_needed = True

        if update_needed:
            logger.info(f"Position {position_id} ({instrument_name}): Updating stop loss at {pip_difference} pips")

            await update_stop_loss_async(
                base_url,
                auth_token,
                selected_account['accNum'],
                position_id,
                entry_price
            )

            # Update tracking data
            tracking_data['last_update'] = time.time()

        # Store updated tracking data
        position_tracking[position_id] = tracking_data

    except Exception as e:
        logger.error(f"Error processing position update: {e}", exc_info=True)
def calculate_pip_difference(entry_price, current_price, instrument_name):
    """
    Calculate pip difference based on the instrument type.
    """
    if instrument_name.endswith("JPY"):
        return round(abs(current_price - entry_price) / 0.01)
    elif instrument_name == "XAUUSD":  # For Gold
        return round(abs(current_price - entry_price) / 0.1)
    else:
        return round(abs(current_price - entry_price) / 0.0001)


async def update_stop_loss_async(base_url, auth_token, acc_num, position_id, new_stop_loss_price):
    """
    Update stop loss asynchronously with retry logic
    """
    url = f"{base_url}/trade/positions/{position_id}"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "accNum": str(acc_num),
        "Content-Type": "application/json"
    }
    body = {"stopLoss": new_stop_loss_price}

    # Retry up to 3 times with exponential backoff
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=body) as response:
                    response.raise_for_status()
                    result = await response.json()
                    logger.info(f"Stop loss updated for position {position_id} to {new_stop_loss_price}")
                    return result
        except aiohttp.ClientError as e:
            if attempt == 2:  # Last attempt
                logger.error(f"Failed to update stop loss after 3 attempts: {e}")
                return None

            # Exponential backoff
            wait_time = 0.5 * (2 ** attempt)
            logger.warning(f"Stop loss update failed, retrying in {wait_time}s: {e}")
            await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"Error updating stop loss: {e}")
            return None