import logging
from colorama import init, Fore, Style
from order_cache import OrderCache
# Initialize colorama
init(autoreset=True)
logger = logging.getLogger(__name__)
# Create a global order cache instance
order_cache = OrderCache()


async def place_orders_batch(orders_client, account_id, acc_num, orders_batch):
    """
    Place a batch of orders using the orders client

    Args:
        orders_client: TradeLocker orders client
        account_id: Account ID
        acc_num: Account number
        orders_batch: List of order details

    Returns:
        dict: Results with successful and failed orders
    """
    try:
        result = await orders_client.place_orders_batch_async(
            account_id,
            acc_num,
            orders_batch
        )
        return result
    except Exception as e:
        logger.error(f"Error placing orders batch: {e}")
        return {
            'successful': [],
            'failed': [(order, str(e)) for order in orders_batch]
        }


async def place_order_with_caching(orders_client, selected_account, instrument_data, parsed_signal,
                                   position_sizes, colored_time, order_type='limit', message_id=None):
    """
    Places orders and stores them in the order cache for future reference.
    Includes entry price in cached data for breakeven functionality.

    Args:
        orders_client: Orders API client
        selected_account: Selected account information
        instrument_data: Instrument data
        parsed_signal: Parsed trading signal
        position_sizes: List of position sizes
        colored_time: Formatted time string for logging
        order_type: Type of order ('limit' or 'market')
        message_id: Telegram message ID for caching

    Returns:
        dict: Results with successful and failed orders
    """
    try:
        # Validate inputs
        if not instrument_data or not parsed_signal or not position_sizes:
            logger.error("Missing required data for order placement")
            return None

        # Check if take profits are available
        take_profits = parsed_signal.get('take_profits', [])
        if not take_profits:
            logger.error("No take profits found in signal")
            return None

        # Extract entry price from the signal for caching
        entry_price = parsed_signal.get('entry_point')

        # Log the message ID we're working with
        logger.info(f"{colored_time}: Processing order with message_id: {message_id}")

        # Calculate total position size
        total_pos_size = sum(float(size) for size in position_sizes)

        # Number of positions based on take profits
        num_positions = len(take_profits)

        # Equal position size distribution if we have a flat value
        if len(position_sizes) == 1 and num_positions > 1:
            position_per_segment = round(total_pos_size / num_positions, 2)
            position_sizes = [position_per_segment] * num_positions
        elif len(position_sizes) != num_positions:
            # Make sure we have the right number of position sizes
            logger.warning(
                f"Position sizes count ({len(position_sizes)}) doesn't match take profits count ({num_positions})")

            # Distribute evenly in this case
            position_per_segment = round(total_pos_size / num_positions, 2)
            position_sizes = [position_per_segment] * num_positions

        # Prepare orders batch
        orders_batch = []

        # Create orders for each take profit
        for i, take_profit in enumerate(take_profits):
            size = position_sizes[i] if i < len(position_sizes) else position_sizes[-1]

            order = {
                'instrument': instrument_data,
                'quantity': size,
                'side': parsed_signal['order_type'],
                'order_type': order_type,
                'price': parsed_signal['entry_point'] if order_type == 'limit' else None,
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': take_profit
            }
            orders_batch.append(order)

            # Log the order details
            runner_note = " (RUNNER)" if i == num_positions - 1 and num_positions > 1 else ""
            logger.info(
                f"{colored_time}: Position #{i + 1}{runner_note} (size: {size}) with take profit: {take_profit}"
            )

        # Place orders in parallel
        logger.info(
            f"{colored_time}: Placing {len(orders_batch)} {Fore.CYAN}{order_type.upper()}{Style.RESET_ALL} orders in parallel..."
        )

        result = await place_orders_batch(
            orders_client,
            selected_account['id'],
            selected_account['accNum'],
            orders_batch
        )

        if result:
            # Extract order IDs from successful orders
            order_ids = []

            # Log results
            successful_orders = result.get('successful', [])
            for j, (order, response) in enumerate(successful_orders):
                entry_point = parsed_signal['entry_point']
                stop_loss = parsed_signal['stop_loss']
                side = parsed_signal['order_type'].upper()
                take_profit = order.get('take_profit', 'N/A')

                # Determine if this is a runner position (last position when multiple positions)
                is_runner = (j == len(successful_orders) - 1) and (len(successful_orders) > 1)
                runner_text = f"{Fore.MAGENTA} (RUNNER){Style.RESET_ALL}" if is_runner else ""

                logger.info(
                    f"{colored_time}: {Fore.GREEN}{order_type.upper()} order placed successfully{runner_text} - "
                    f"Instrument: {Fore.YELLOW}{instrument_data['name']}{Style.RESET_ALL}, "
                    f"Side: {Fore.BLUE}{side}{Style.RESET_ALL}, "
                    f"Size: {Fore.YELLOW}{order.get('quantity')}{Style.RESET_ALL}, "
                    f"Entry: {Fore.YELLOW}{entry_point}{Style.RESET_ALL}, "
                    f"SL: {Fore.RED}{stop_loss}{Style.RESET_ALL}, "
                    f"TP: {Fore.GREEN}{take_profit}{Style.RESET_ALL}"
                )

                # Extract order ID and add to our list
                order_id = None
                try:
                    if isinstance(response, dict):
                        if 'd' in response and 'orderId' in response.get('d', {}):
                            order_id = response['d']['orderId']
                        elif 'orderId' in response:
                            order_id = response['orderId']

                        if order_id:
                            order_ids.append(order_id)
                            logger.debug(f"Extracted order ID: {order_id}")
                except Exception as e:
                    logger.error(f"Error extracting order ID: {e}")

            # Log failed orders
            for order, error in result.get('failed', []):
                logger.error(f"{colored_time}: {Fore.RED}Failed to place order{Style.RESET_ALL}: {error}")

            # Store orders in cache if we have a message_id and order_ids
            if message_id and order_ids:
                logger.info(f"{colored_time}: Attempting to cache {len(order_ids)} orders for message {message_id}")

                # Make sure we're using the global order cache
                from order_cache import OrderCache
                order_cache = OrderCache()

                # Store in cache with explicit call including entry price
                cached = order_cache.store_orders(
                    message_id=str(message_id),  # Ensure it's a string
                    order_ids=order_ids,
                    take_profits=take_profits,
                    instrument=instrument_data['name'],
                    entry_price=entry_price  # Store entry price for breakeven functionality
                )

                if cached:
                    logger.info(
                        f"{colored_time}: {Fore.CYAN}Successfully cached {len(order_ids)} orders for message {message_id} with entry price {entry_price}{Style.RESET_ALL}"
                    )
                else:
                    logger.warning(f"{colored_time}: Failed to cache orders for message {message_id}")
            else:
                logger.warning(
                    f"{colored_time}: Cannot cache orders - missing message ID ({message_id}) or order IDs ({len(order_ids)})")

            return result
        else:
            logger.error(f"{colored_time}: Failed to place orders batch.")
            return None

    except Exception as e:
        logger.error(f"{colored_time}: Error placing orders: {e}", exc_info=True)
        return None

async def place_orders_with_risk_check(orders_client, accounts_client, quotes_client, selected_account,
                                       instrument_data, parsed_signal, position_sizes, risk_amount,
                                       max_drawdown_balance, colored_time, message_id=None):
    """
    Place orders with risk checks and cache the order IDs with message ID.

    Args:
        orders_client: Orders API client
        accounts_client: Accounts API client
        quotes_client: Quotes API client
        selected_account: Selected account info
        instrument_data: Instrument data
        parsed_signal: Parsed signal
        position_sizes: Position sizes
        risk_amount: Risk amount
        max_drawdown_balance: Max drawdown balance
        colored_time: Formatted time
        message_id: Message ID for caching

    Returns:
        dict: Result of order placement
    """
    try:
        # Refresh account balance
        updated_account = await accounts_client.refresh_account_balance_async()
        if not updated_account:
            logger.error(f"{colored_time}: Failed to refresh account balance")
            return None

        # Get latest balance
        latest_balance = float(updated_account['accountBalance'])

        # Check drawdown limits
        if latest_balance - risk_amount < max_drawdown_balance:
            logger.warning(
                f"{colored_time}: Balance {latest_balance} has reached or exceeded "
                f"max draw down balance {max_drawdown_balance}. Skipping order placement."
            )
            return None

        # Default to limit order
        order_type = 'limit'
        adjusted_stop_loss = parsed_signal['stop_loss']

        # Get current market price to decide between limit and market order
        try:
            # Use instrument_data['name'] (the broker's actual instrument name)
            broker_instrument_name = instrument_data['name']
            quote = await quotes_client.get_quote_async(updated_account, broker_instrument_name)

            if quote and 'd' in quote:
                # Extract bid and ask prices
                bid_price = float(quote['d'].get('bp', 0))
                ask_price = float(quote['d'].get('ap', 0))

                # Determine current price based on order type (buy/sell)
                side = parsed_signal['order_type'].lower()
                current_price = ask_price if side == 'buy' else bid_price

                # Determine pip value based on instrument
                if broker_instrument_name.upper().endswith("JPY") or "JPY" in broker_instrument_name.upper():
                    pip_value = 0.01
                elif broker_instrument_name.upper() in ["DJI30", "DOW", "US30"]:
                    pip_value = 1.0
                elif any(gold in broker_instrument_name.upper() for gold in ["XAUUSD", "GOLD"]):
                    pip_value = 0.1
                else:
                    pip_value = 0.0001

                # Calculate price difference
                price_diff = abs(parsed_signal['entry_point'] - current_price)

                # Convert to pips
                pip_diff = round(price_diff / pip_value)

                # Check if within threshold for market order
                threshold_pips = 10  # If within 10 pips, use market order
                if pip_diff <= threshold_pips:
                    order_type = 'market'

                    # Adjust stop loss: add diff for buy, subtract for sell
                    if side == 'buy':
                        adjusted_stop_loss = parsed_signal['stop_loss'] + price_diff
                    else:  # sell
                        adjusted_stop_loss = parsed_signal['stop_loss'] - price_diff

                    logger.info(
                        f"{colored_time}: Using {Fore.GREEN}MARKET {side.upper()}{Style.RESET_ALL} instead of limit. "
                        f"Current price: {Fore.YELLOW}{current_price}{Style.RESET_ALL}, "
                        f"Entry: {Fore.YELLOW}{parsed_signal['entry_point']}{Style.RESET_ALL}, "
                        f"Diff: {Fore.CYAN}{pip_diff} pips{Style.RESET_ALL}, "
                        f"Adjusted SL: {Fore.MAGENTA}{adjusted_stop_loss}{Style.RESET_ALL}"
                    )
            else:
                logger.warning(f"{colored_time}: Could not get current price. Using limit order.")
        except Exception as e:
            logger.warning(f"{colored_time}: Error getting current price: {e}. Using limit order.")

        # Create a copy of parsed_signal with adjusted stop loss
        modified_signal = parsed_signal.copy()
        modified_signal['stop_loss'] = adjusted_stop_loss

        # Update instrument name in modified_signal to use broker's name
        modified_signal['instrument'] = instrument_data['name']

        # Proceed with order placement using the caching version
        return await place_order_with_caching(
            orders_client, updated_account, instrument_data,
            modified_signal, position_sizes, colored_time,
            order_type=order_type, message_id=message_id
        )

    except Exception as e:
        logger.error(f"{colored_time}: Error in order placement with risk check: {e}", exc_info=True)
        return None