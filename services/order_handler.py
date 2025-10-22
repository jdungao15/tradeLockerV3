import logging
from colorama import init, Fore, Style
from config.order_cache import OrderCache
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


"""
Complete place_order_with_caching function with automatic margin management
Replace your entire place_order_with_caching function in services/order_handler.py with this
"""

"""
Complete place_order_with_caching function with automatic margin management
Replace your entire place_order_with_caching function in services/order_handler.py with this
"""


async def place_order_with_caching(orders_client, selected_account, instrument_data, parsed_signal,
                                   position_sizes, colored_time, order_type='limit', message_id=None):
    """
    Places orders and stores them in the order cache for future reference.
    Includes automatic margin management - will retry with reduced sizes if margin insufficient.
    Includes entry price in cached data for breakeven functionality.

    MODIFIED: CFD instruments now use only 2 positions (TP2 and TP3) with TP3 as runner (no 500-pip offset)

    Args:
        orders_client: TradeLocker orders client
        selected_account: Selected account info
        instrument_data: Instrument data
        parsed_signal: Parsed signal containing order details
        position_sizes: List of position sizes for each take profit
        colored_time: Formatted timestamp string
        order_type: 'limit' or 'market'
        message_id: Optional message ID for caching orders

    Returns:
        dict: Results with placed and failed orders
    """
    try:
        account_id = selected_account['id']
        acc_num = selected_account['accNum']
        instrument_name = instrument_data['name']
        instrument_type = instrument_data.get('type', 'UNKNOWN')

        # Extract signal information
        # Handle order types with modifiers (e.g., 'buy limit', 'sell stop')
        order_type_lower = parsed_signal['order_type'].lower()
        order_side = 'buy' if 'buy' in order_type_lower else 'sell'
        entry_point = parsed_signal['entry_point']
        stop_loss = parsed_signal['stop_loss']
        take_profits = parsed_signal['take_profits']

        # Log order placement start
        logger.debug(f"{colored_time}: Instrument {instrument_name} is {instrument_type}")

        # Determine if this is a CFD and handle accordingly
        is_cfd = instrument_type in ['EQUITY_CFD', 'INDEX_CFD', 'COMMODITY_CFD']

        if is_cfd:
            logger.info(f"{colored_time}: Processing CFD instrument with 2-position runner allocation")

            # For CFDs, sort TPs based on order direction
            if order_side == 'buy':
                sorted_tps = sorted(take_profits, reverse=True)  # Descending for buy
            else:
                sorted_tps = sorted(take_profits)  # Ascending for sell

            logger.info(
                f"{colored_time}: Sorted TPs ({'descending' if order_side == 'buy' else 'ascending'}): {sorted_tps}")

            # MODIFIED: Use only 2 positions - TP2 and TP3 (no 500-pip offset)
            # Ensure we have at least 3 TPs to work with
            if len(sorted_tps) < 3:
                logger.error(f"{colored_time}: Need at least 3 take profits for CFD strategy, got {len(sorted_tps)}")
                return None

            # For SELL: sorted_tps is ascending [4240, 4265, 4272], we want 4265 and 4240
            # For BUY: sorted_tps is descending [4272, 4265, 4240], we want 4265 and 4240
            # In both cases: index[1] is TP2, index[0] is TP3 (furthest/runner)
            tp_for_pos1 = sorted_tps[1]  # Second TP (middle one)
            tp_for_pos2 = sorted_tps[0]  # Third TP (furthest one - runner)

            # Adjust position_sizes to only use last 2
            if len(position_sizes) > 2:
                position_sizes = position_sizes[-2:]  # Take last 2 sizes
            elif len(position_sizes) == 1:
                # Split equally if only one size given
                pos_size = round(float(position_sizes[0]) / 2, 2)
                position_sizes = [pos_size, pos_size]

            # Create final TPs list with only 2 positions
            final_tps = [tp_for_pos1, tp_for_pos2]

            # Log the positions
            logger.info(f"{colored_time}: Position #1 (size: {position_sizes[0]}) with take profit: {tp_for_pos1}")
            logger.info(
                f"{colored_time}: Position #2 (RUNNER) (size: {position_sizes[1]}) with take profit: {tp_for_pos2}")

        else:
            # For non-CFD instruments (Forex), use standard approach
            final_tps = take_profits

        # Log order placement
        logger.debug(f"{colored_time}: Placing {len(position_sizes)} {order_type.upper()} orders in parallel...")

        # ========================================================================
        # AUTOMATIC MARGIN MANAGEMENT - Retry with reduced sizes if needed
        # ========================================================================

        import asyncio

        # Get original sizes
        current_sizes = position_sizes.copy()
        max_retries = 3
        responses = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                # Reduce all sizes by 50%
                logger.warning(
                    f"{colored_time}: {Fore.YELLOW}Margin insufficient. "
                    f"Retry {attempt}/{max_retries} - Reducing sizes by 50%{Style.RESET_ALL}"
                )
                current_sizes = [round(size * 0.5, 2) for size in current_sizes]

                # Check if sizes are too small
                min_size = instrument_data.get('minTrade', 0.01)
                if any(s < min_size for s in current_sizes):
                    logger.error(
                        f"{colored_time}: {Fore.RED}Position sizes below minimum ({min_size}). "
                        f"Cannot place orders.{Style.RESET_ALL}"
                    )
                    break

                logger.info(f"{colored_time}: New sizes: {current_sizes}")

            # Attempt to place orders using create_order_async
            tasks = []
            for size, tp in zip(current_sizes, final_tps):
                task = orders_client.create_order_async(
                    account_id=account_id,
                    acc_num=acc_num,
                    instrument=instrument_data,  # Pass entire instrument dict
                    quantity=size,
                    side=order_side,
                    order_type=order_type,
                    price=entry_point if order_type == 'limit' else None,
                    stop_loss=stop_loss,
                    take_profit=tp
                )
                tasks.append(task)

            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # Count margin errors and successes
            margin_errors = 0
            success_count = 0

            for response in responses:
                if isinstance(response, dict):
                    error_msg = str(response.get('errmsg', '')).lower()
                    if response.get('s') == 'error' and 'not enough margin' in error_msg:
                        margin_errors += 1
                    elif response.get('s') == 'ok':
                        success_count += 1

            logger.debug(
                f"{colored_time}: Attempt {attempt + 1}: "
                f"{success_count} successful, "
                f"{margin_errors} margin errors"
            )

            # If no margin errors or at least one success, we're done
            if margin_errors == 0 or success_count > 0:
                logger.debug(
                    f"{colored_time}: [OK] Completed with {success_count}/{len(current_sizes)} orders placed"
                )
                break

            # If all failed due to margin and we have retries left, continue
            if attempt < max_retries:
                logger.warning(
                    f"{colored_time}: {Fore.YELLOW}All {len(current_sizes)} orders failed due to margin. "
                    f"Retrying with smaller sizes...{Style.RESET_ALL}"
                )
                await asyncio.sleep(0.5)  # Brief delay before retry
            else:
                logger.error(
                    f"{colored_time}: {Fore.RED}Failed after {max_retries} retries. "
                    f"No orders placed.{Style.RESET_ALL}"
                )

        # ========================================================================
        # Process results
        # ========================================================================

        if responses:
            result = {
                'placed': [],
                'failed': []
            }

            order_ids = []

            for i, response in enumerate(responses):
                # Handle exceptions
                if isinstance(response, Exception):
                    logger.error(f"{colored_time}: Order placement exception: {response}")
                    result['failed'].append((None, str(response)))
                    continue

                # Handle successful orders
                if isinstance(response, dict) and response.get('s') == 'ok':
                    if 'd' in response and 'orderId' in response['d']:
                        order_id = response['d']['orderId']
                        order_ids.append(order_id)
                        result['placed'].append((None, response))

                        # Log success with appropriate styling
                        tp_value = final_tps[i]
                        size_value = current_sizes[i]

                        # Check if this is a runner position (last position for CFD)
                        is_runner = (is_cfd and i == len(responses) - 1)

                        runner_tag = " (RUNNER)" if is_runner else ""
                        logger.info(
                            f"{colored_time}: ✅ {order_type.upper()} order placed{runner_tag} - "
                            f"{instrument_name} {order_side.upper()} {size_value} lots @ {entry_point}, "
                            f"SL: {stop_loss}, TP: {tp_value}"
                        )
                    else:
                        logger.error(f"{colored_time}: Order response missing orderId: {response}")
                        result['failed'].append((None, "Missing orderId in response"))

                # Handle failed orders
                elif isinstance(response, dict) and response.get('s') == 'error':
                    error_msg = response.get('errmsg', 'Unknown error')
                    result['failed'].append((None, error_msg))
                    logger.error(f"{colored_time}: {Fore.RED}Order failed{Style.RESET_ALL}: {error_msg}")

            # Log runner position if CFD
            if is_cfd and result['placed']:
                logger.info(
                    f"{colored_time}: {Fore.MAGENTA}CFD Runner position{Style.RESET_ALL} "
                    f"(ID: {order_ids[-1] if order_ids else 'N/A'}) created - "
                    f"Position monitor will handle trailing stop"
                )

            # Store orders in cache if we have a message_id and order_ids
            if message_id and order_ids:
                logger.debug(f"{colored_time}: Attempting to cache {len(order_ids)} orders for message {message_id}")

                # Make sure we're using the global order cache
                from config.order_cache import OrderCache
                order_cache = OrderCache()

                # Store in cache with explicit call including entry price
                cached = order_cache.store_orders(
                    message_id=str(message_id),
                    order_ids=order_ids,
                    take_profits=take_profits,
                    instrument=instrument_name,
                    entry_price=entry_point
                )

                if cached:
                    logger.debug(
                        f"{colored_time}: Successfully cached {len(order_ids)} orders "
                        f"for message {message_id} with entry price {entry_point}"
                    )
                else:
                    logger.warning(f"{colored_time}: Failed to cache orders for message {message_id}")
            else:
                logger.warning(
                    f"{colored_time}: Cannot cache orders - "
                    f"missing message ID ({message_id}) or order IDs ({len(order_ids) if order_ids else 0})"
                )

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
    """Place orders with risk checks and signal validation"""

    try:
        # ======= NEW CODE - ADD THIS BLOCK AT THE TOP =======
        from services.signal_validator import SignalValidator

        validator = SignalValidator()
        validation_result = await validator.validate_signal_before_execution(
            quotes_client=quotes_client,
            selected_account=selected_account,
            instrument_data=instrument_data,
            parsed_signal=parsed_signal,
            signal_timestamp=None  # You can pass actual timestamp if available
        )

        # If signal is invalid, return immediately
        if not validation_result['valid']:
            # Already logged by signal_validator
            return None

        # Use the validated order type (market or limit)
        order_type = validation_result.get('order_type', 'limit')

        # If using market order, adjust entry price
        if order_type == 'market' and 'adjusted_entry' in validation_result:
            parsed_signal = parsed_signal.copy()
            parsed_signal['entry_point'] = validation_result['adjusted_entry']

            logger.info(
                f"{colored_time}: {Fore.CYAN}Using MARKET order at {validation_result['adjusted_entry']} "
                f"(Signal price: {parsed_signal['entry_point']}, "
                f"Slippage: {validation_result['price_diff_pips']:.1f} pips){Style.RESET_ALL}"
            )
        # ======= END NEW CODE =======

        # Refresh account balance (YOUR EXISTING CODE CONTINUES HERE)
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

                    # Round to 5 decimal places to avoid floating point precision issues
                    adjusted_stop_loss = round(adjusted_stop_loss, 5)

                    logger.debug(
                        f"{colored_time}: Using MARKET {side.upper()} instead of limit. "
                        f"Current price: {current_price}, "
                        f"Entry: {parsed_signal['entry_point']}, "
                        f"Diff: {pip_diff} pips, "
                        f"Adjusted SL: {adjusted_stop_loss}"
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
