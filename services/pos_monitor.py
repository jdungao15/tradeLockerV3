import asyncio
import aiohttp
import logging
import time

logger = logging.getLogger(__name__)


async def monitor_existing_position(accounts_client, instruments_client, quotes_client,
                                    orders_client, selected_account, base_url, auth_token):
    """
    Function to check and monitor any existing open positions asynchronously with improved error handling.
    """
    account_id = selected_account['id']
    acc_num = selected_account['accNum']

    # Local cache to avoid repeated lookups
    instrument_cache = {}
    position_tracking = {}  # Track position updates to avoid redundant API calls

    # Add counters for error handling and backoff
    failure_counter = 0
    max_failures = 10  # Maximum consecutive failures before backing off
    backoff_time = 300  # 5 minutes backoff after max failures
    normal_poll_interval = 10  # 10 seconds when no positions
    active_poll_interval = 3  # 3 seconds when positions exist

    logger.info("Starting position monitoring service")

    while True:
        try:
            logger.debug("Checking for open positions...")

            # Get current positions
            positions = await accounts_client.get_current_position_async(account_id, acc_num)

            if positions and positions.get('d', {}).get('positions'):
                # Reset failure counter on success
                failure_counter = 0

                position_data_list = positions['d']['positions']

                # Process positions in parallel for efficiency
                await process_positions_parallel(
                    position_data_list,
                    instruments_client,
                    quotes_client,
                    orders_client,
                    selected_account,
                    base_url,
                    auth_token,
                    instrument_cache,
                    position_tracking
                )

                # Short polling interval when positions exist
                await asyncio.sleep(active_poll_interval)
            else:
                # Check if it's a valid empty response or an error
                if positions is not None:
                    # Valid response with no positions
                    logger.debug("No open positions found")
                    failure_counter = 0
                    await asyncio.sleep(normal_poll_interval)
                else:
                    # Error response (positions is None)
                    failure_counter += 1
                    logger.warning(f"Position monitoring failure: {failure_counter}/{max_failures}")

                    # Implement progressive backoff based on failure counter
                    if failure_counter >= max_failures:
                        logger.error(f"Too many position monitoring failures. Backing off for {backoff_time} seconds")
                        await asyncio.sleep(backoff_time)
                        # Reset counter after backoff
                        failure_counter = max(0, failure_counter - 5)  # Reduce but don't fully reset
                    else:
                        # Incremental backoff for intermittent failures
                        backoff = min(30, 2 ** failure_counter)  # Exponential backoff with max of 30 seconds
                        await asyncio.sleep(backoff)

        except Exception as e:
            logger.error(f"Error in position monitoring: {e}", exc_info=True)
            failure_counter += 1

            # Implement backoff for exceptions
            if failure_counter >= max_failures:
                logger.error(
                    f"Position monitoring backing off for {backoff_time} seconds after {failure_counter} consecutive failures")
                await asyncio.sleep(backoff_time)
                # Partially reset counter after backoff
                failure_counter = max(0, failure_counter - 5)
            else:
                # Incremental backoff
                backoff = min(60, 3 ** (failure_counter // 2))  # More aggressive backoff for exceptions
                await asyncio.sleep(backoff)


async def process_positions_parallel(positions, instruments_client, quotes_client,
                                     orders_client, selected_account, base_url, auth_token,
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
                orders_client,
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
                                  orders_client, selected_account, base_url, auth_token,
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
            position_tracking,
            orders_client
        )

    except Exception as e:
        logger.error(f"Error monitoring position {position_data[0]}: {e}", exc_info=True)


async def process_position_update(position_id, instrument_data, side, entry_price,
                                  quote_data, selected_account, base_url, auth_token,
                                  position_tracking, orders_client):
    """
    Process position updates for the runner position (3rd position).
    Applies trailing stop when first take profit is hit, using the distance
    between entry and second take profit as the trailing offset.
    """
    try:
        instrument_name = instrument_data['name']
        instrument_id = instrument_data.get('tradableInstrumentId', '')
        ask_price = float(quote_data['d'].get('ap', 0))
        bid_price = float(quote_data['d'].get('bp', 0))

        # For a 'buy' position, the current price is the bid price (what you can sell for)
        # For a 'sell' position, the current price is the ask price (what you can buy for)
        current_price = bid_price if side.lower() == 'buy' else ask_price

        # Get or initialize position tracking data
        tracking_data = position_tracking.get(position_id, {
            'last_update': 0,
            'trailing_activated': False,
            'is_runner': False,
            'take_profits': [],  # Store the take profit levels here
            'original_order_id': ''  # Store original order ID for reference
        })

        # Store basic position info
        tracking_data['instrument_name'] = instrument_name
        tracking_data['position_id'] = position_id
        tracking_data['side'] = side
        tracking_data['entry_price'] = entry_price

        # Check if this is the 3rd position (runner)
        if 'is_runner_checked' not in tracking_data:
            tracking_data['is_runner_checked'] = True

            # Identify runner position (3rd position)
            if position_id.endswith('3') or 'runner' in str(position_id).lower():
                tracking_data['is_runner'] = True
                logger.info(
                    f"Position {position_id} ({instrument_name}) identified as runner - will apply trailing stop when TP1 hit")

                # If take_profits not stored yet, we need to get them from order history
                if not tracking_data.get('take_profits'):
                    # Get take profit levels from your system
                    take_profits = await get_take_profits_for_position(
                        position_id, instrument_id, selected_account, orders_client
                    )

                    if take_profits and len(take_profits) >= 2:
                        tracking_data['take_profits'] = take_profits
                        logger.info(f"Stored take profit levels for position {position_id}: {take_profits}")
                    else:
                        logger.warning(f"Could not retrieve take profit levels for position {position_id}")

        # Skip if not a runner position
        if not tracking_data.get('is_runner', False):
            position_tracking[position_id] = tracking_data
            return

        # Skip if no take profit levels stored
        if not tracking_data.get('take_profits') or len(tracking_data['take_profits']) < 2:
            # Even for runner positions, we need at least TP1 and TP2 to implement the strategy
            position_tracking[position_id] = tracking_data
            return

        # Get take profit levels
        tp1 = tracking_data['take_profits'][0]
        tp2 = tracking_data['take_profits'][1]

        # Current time for rate limiting
        current_time = time.time()
        last_update_time = tracking_data.get('last_update', 0)
        time_since_update = current_time - last_update_time

        # Only proceed if enough time has passed since last update (rate limiting)
        if time_since_update < 30:  # 30 second minimum between updates
            position_tracking[position_id] = tracking_data
            return

        # Check if TP1 has been hit
        tp1_hit = False
        if side.lower() == 'buy':
            # For buy: TP1 is hit if current price >= TP1
            tp1_hit = current_price >= tp1
        else:  # 'sell'
            # For sell: TP1 is hit if current price <= TP1
            tp1_hit = current_price <= tp1

        # Activate trailing stop when TP1 is hit and trailing stop not already activated
        if tp1_hit and not tracking_data.get('trailing_activated', False):
            logger.info(
                f"Position {position_id} ({instrument_name}): First take profit hit. "
                f"Current price: {current_price}, TP1: {tp1}. Moving SL to breakeven and activating trailing stop."
            )

            # Step 1: Move stop loss to entry price (breakeven protection)
            # Step 2: Enable trailing stop to protect further profits

            # Calculate trailing offset: distance between current price and entry
            # This will make the SL start at entry and trail from there
            # For example: Entry=2500, TP1=2550 → trailing offset = 50 pips
            # So when price is at 2550, SL is at 2500 (entry)
            # When price goes to 2560, SL trails to 2510 (still 50 pips behind)
            current_profit_distance = abs(current_price - entry_price)

            # Use the FULL distance from TP1 to entry as trailing offset
            # This ensures SL starts exactly at entry level when TP1 is hit
            trailing_distance = current_profit_distance

            # Convert to points for the API
            trailing_offset = calculate_trailing_offset(instrument_name, trailing_distance)

            logger.info(
                f"Moving SL to breakeven (entry: {entry_price}) with trailing offset: {trailing_offset} points"
            )

            # Make the API call to set stop loss to entry + enable trailing
            url = f"{base_url}/trade/positions/{position_id}"
            headers = {
                "Authorization": f"Bearer {auth_token}",
                "accNum": str(selected_account['accNum']),
                "Content-Type": "application/json"
            }

            # Update stop loss to entry price AND enable trailing
            body = {
                "stopLoss": entry_price,          # Move SL to entry (breakeven)
                "trailingOffset": trailing_offset  # Enable trailing from here
            }

            # Make the API call
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.patch(url, headers=headers, json=body) as response:
                        if response.status == 200:
                            tracking_data['trailing_activated'] = True
                            tracking_data['last_update'] = current_time
                            logger.info(
                                f"✅ Successfully moved SL to breakeven and activated trailing stop "
                                f"for position {position_id} (Entry: {entry_price}, Trailing: {trailing_offset} points)"
                            )
                        else:
                            error_text = await response.text()
                            logger.error(f"Failed to activate trailing stop: {response.status} - {error_text}")
            except Exception as e:
                logger.error(f"Error activating trailing stop: {e}")

        # Store updated tracking data
        position_tracking[position_id] = tracking_data

    except Exception as e:
        logger.error(f"Error processing position update: {e}", exc_info=True)


async def get_take_profits_for_position(position_id, instrument_id, selected_account, orders_client):
    """
    Helper function to retrieve the take profit levels for a position.

    This function gets the take profit levels by:
    1. Looking for the orders that created this position
    2. Extracting the take profit levels from these orders
    3. Sorting them appropriately based on the order side
    """
    try:
        # Get recent orders for this instrument
        orders = await orders_client.get_orders_async(
            selected_account['id'],
            selected_account['accNum']
        )

        if not orders or 'd' not in orders or 'orders' not in orders['d']:
            return None

        # Find the order that created this position
        position_orders = []
        for order in orders['d']['orders']:
            # Check if this order is related to the position
            # You may need to adjust this logic based on how orders and positions are linked
            if str(order.get('positionId', '')) == str(position_id):
                position_orders.append(order)

        # Extract take profit levels
        take_profits = []
        for order in position_orders:
            # Extract take profit from order
            tp = order.get('takeProfit')
            if tp and tp not in take_profits:
                take_profits.append(float(tp))

        # Sort take profits appropriately based on side
        # For buy orders: ascending order, for sell orders: descending order
        side = position_orders[0].get('side', '').lower() if position_orders else 'buy'
        take_profits.sort(reverse=(side == 'sell'))

        return take_profits

    except Exception as e:
        logger.error(f"Error retrieving take profits for position {position_id}: {e}")
        return None


def calculate_trailing_offset(instrument_name, price_distance):
    """
    Calculate trailing stop offset value for TradeLocker API.
    Converts price distance to points as expected by the API.

    Supports: Forex, Indices, Metals (Gold/Silver), and Crypto
    """
    instrument_upper = instrument_name.upper()

    # For indices (1:1 ratio - price distance = points)
    if any(index_name in instrument_upper for index_name in
           ["DJI30", "DOW", "US30", "NDX100", "NAS100", "NASDAQ",
            "SPX500", "SP500", "S&P", "GER30", "DAX",
            "UK100", "FTSE", "JPN225", "NIKKEI",
            "AUS200", "HK50", "HANGSENG"]):
        return int(price_distance)

    # For crypto (similar to indices - 1:1 ratio)
    elif any(crypto in instrument_upper for crypto in
             ["BTC", "BITCOIN", "ETH", "ETHEREUM", "LTC", "LITECOIN",
              "XRP", "RIPPLE", "ADA", "CARDANO", "SOL", "SOLANA"]):
        return int(price_distance)

    # For gold and silver (multiply by 100)
    elif any(name in instrument_upper for name in
             ["XAUUSD", "GOLD", "XAU", "XAGUSD", "SILVER", "XAG"]):
        return int(price_distance * 100)

    # For JPY pairs (multiply by 100)
    elif instrument_upper.endswith("JPY"):
        return int(price_distance * 100)

    # For standard forex pairs (multiply by 10000)
    else:
        # Standard forex (EUR/USD, GBP/USD, etc.)
        return int(price_distance * 10000)
