import logging
import asyncio
from typing import List, Dict, Any
from colorama import init, Fore, Style

# Initialize colorama
init(autoreset=True)

logger = logging.getLogger(__name__)

def place_order(orders_client, selected_account, instrument_data, parsed_signal, position_sizes, colored_time):
    """
    Places orders for the given instrument and parsed signal - synchronous version.
    """
    try:
        for position_size, take_profit in zip(position_sizes, parsed_signal['take_profits']):
            order_params = {
                'account_id': selected_account['id'],
                'acc_num': selected_account['accNum'],
                'instrument': instrument_data,
                'quantity': position_size,
                'side': parsed_signal['order_type'],
                'order_type': 'limit',
                'price': parsed_signal['entry_point'],
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': take_profit,
            }

            logger.info("Placing order...")
            order_response = orders_client.create_order(**order_params)
            if order_response:
                logger.info(f"{colored_time}: Order placed successfully: {order_response}")
            else:
                logger.error(f"{colored_time}: Failed to place order.")

    except Exception as e:
        logger.error(f"{colored_time}: Error placing order: {e}")


async def place_order_async(orders_client, selected_account, instrument_data, parsed_signal, position_sizes,
                            colored_time):
    """
    Places orders for the given instrument and parsed signal - asynchronous version.

    Args:
        orders_client: Asynchronous orders client
        selected_account: Account information dictionary
        instrument_data: Instrument data dictionary
        parsed_signal: Parsed trading signal
        position_sizes: List of position sizes
        colored_time: Formatted time string for logging
    """
    try:
        # Prepare order batch
        orders_batch = []

        for position_size, take_profit in zip(position_sizes, parsed_signal['take_profits']):
            order = {
                'instrument': instrument_data,
                'quantity': position_size,
                'side': parsed_signal['order_type'],
                'order_type': 'limit',
                'price': parsed_signal['entry_point'],
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': take_profit,
            }
            orders_batch.append(order)

        # Place orders in parallel
        logger.info(f"{colored_time}: Placing {len(orders_batch)} orders in parallel...")

        result = await orders_client.place_orders_batch_async(
            selected_account['id'],
            selected_account['accNum'],
            orders_batch
        )

        if result:
            # Log results
            for order, response in result.get('successful', []):
                logger.info(f"{colored_time}: Order placed successfully: {response}")

            for order, error in result.get('failed', []):
                logger.error(f"{colored_time}: Failed to place order: {error}")

            return result
        else:
            logger.error(f"{colored_time}: Failed to place orders batch.")
            return None

    except Exception as e:
        logger.error(f"{colored_time}: Error placing orders: {e}", exc_info=True)
        return None


async def place_orders_with_risk_check(orders_client, accounts_client, quotes_client, selected_account,
                                       instrument_data, parsed_signal, position_sizes, risk_amount,
                                       max_drawdown_balance, colored_time):
    """
    Place orders with additional risk management checks and smart order type selection

    Args:
        orders_client: Orders API client
        accounts_client: Accounts API client
        quotes_client: Quotes API client for real-time prices
        selected_account: Selected account information
        instrument_data: Instrument data
        parsed_signal: Parsed trading signal
        position_sizes: List of position sizes
        risk_amount: Amount at risk
        max_drawdown_balance: Maximum drawdown balance
        colored_time: Formatted time string for logging

    Returns:
        Dictionary with order results or None if risk check failed
    """
    try:
        # First refresh account balance
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
        quote = await quotes_client.get_quote_async(updated_account, parsed_signal['instrument'])

        if quote and 'd' in quote:
            # Extract bid and ask prices
            bid_price = float(quote['d'].get('bp', 0))
            ask_price = float(quote['d'].get('ap', 0))

            # Determine current price based on order type (buy/sell)
            side = parsed_signal['order_type'].lower()
            current_price = ask_price if side == 'buy' else bid_price

            # Determine pip value based on instrument
            if instrument_data['name'].endswith("JPY"):
                pip_value = 0.01
            elif instrument_data['name'] == "DJI30":
                pip_value = 1.0
            elif instrument_data['name'] == "XAUUSD":
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

        # Create a copy of parsed_signal with adjusted stop loss
        modified_signal = parsed_signal.copy()
        modified_signal['stop_loss'] = adjusted_stop_loss

        # Proceed with order placement
        return await place_order_async(
            orders_client, updated_account, instrument_data,
            modified_signal, position_sizes, colored_time, order_type=order_type
        )

    except Exception as e:
        logger.error(f"{colored_time}: Error in order placement with risk check: {e}", exc_info=True)
        return None


async def place_order_async(orders_client, selected_account, instrument_data, parsed_signal, position_sizes,
                            colored_time, order_type='limit'):
    """
    Places orders for the given instrument and parsed signal - asynchronous version.
    """
    try:
        # Prepare order batch - only include positions with non-zero size
        orders_batch = []

        # Check if this is a CFD instrument
        is_cfd = instrument_data['type'] == "EQUITY_CFD"
        logger.info(f"{colored_time}: Instrument {instrument_data['name']} is {'CFD' if is_cfd else 'non-CFD'}")

        if is_cfd:
            # For CFD instruments, we need to place exactly 3 orders with specific take profits
            logger.info(f"{colored_time}: Processing CFD instrument with custom take profit allocation")

            # Get total position size (sum of all non-zero positions)
            valid_positions = [(size, tp) for size, tp in zip(position_sizes, parsed_signal['take_profits']) if
                               size > 0]
            total_pos_size = sum(size for size, _ in valid_positions)

            # Calculate position size per segment (equal allocation)
            position_per_segment = round(total_pos_size / 3, 2)

            # Get order direction
            is_buy = parsed_signal['order_type'].lower() == 'buy'

            # Sort take profits in the right order based on order type
            # For SELL: We want lowest TPs first (ascending)
            # For BUY: We want highest TPs first (descending)
            sorted_tps = sorted(parsed_signal['take_profits'], reverse=is_buy)
            logger.info(f"{colored_time}: Sorted TPs ({('descending' if is_buy else 'ascending')}): {sorted_tps}")

            # Select the two most favorable take profits
            # (For SELL: The two lowest values, for BUY: The two highest values)
            if len(sorted_tps) >= 2:
                tp1 = sorted_tps[0]  # First TP (closest to entry)
                tp2 = sorted_tps[1]  # Second TP
            elif len(sorted_tps) == 1:
                tp1 = sorted_tps[0]
                tp2 = sorted_tps[0]
            else:
                logger.error(f"{colored_time}: No take profits found in signal, cannot place orders")
                return None

            # Create order 1 with first TP
            order1 = {
                'instrument': instrument_data,
                'quantity': position_per_segment,
                'side': parsed_signal['order_type'],
                'order_type': order_type,
                'price': parsed_signal['entry_point'] if order_type == 'limit' else None,
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': tp1
            }
            orders_batch.append(order1)
            logger.info(f"{colored_time}: Position #1 (size: {position_per_segment}) with take profit: {tp1}")

            # Create order 2 with second TP
            order2 = {
                'instrument': instrument_data,
                'quantity': position_per_segment,
                'side': parsed_signal['order_type'],
                'order_type': order_type,
                'price': parsed_signal['entry_point'] if order_type == 'limit' else None,
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': tp2
            }
            orders_batch.append(order2)
            logger.info(f"{colored_time}: Position #2 (size: {position_per_segment}) with take profit: {tp2}")

            # Create order 3 (runner) with 500 pip distant take profit
            side = parsed_signal['order_type'].lower()
            entry = float(parsed_signal['entry_point'])

            # Determine pip size based on instrument
            if instrument_data['name'] == "DJI30":
                pip_value = 1.0
            elif instrument_data['name'] == "NDX100":
                pip_value = 1.0
            elif instrument_data['name'] == "XAUUSD":
                pip_value = 0.1
            else:
                pip_value = 1.0  # Default for other CFDs

            # Set take profit 500 pips away from entry
            pips_distance = 500 * pip_value

            if side == 'buy':
                far_tp = entry + pips_distance
            else:  # 'sell'
                far_tp = entry - pips_distance

            order3 = {
                'instrument': instrument_data,
                'quantity': position_per_segment,
                'side': parsed_signal['order_type'],
                'order_type': order_type,
                'price': parsed_signal['entry_point'] if order_type == 'limit' else None,
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': far_tp
            }
            orders_batch.append(order3)
            logger.info(
                f"{colored_time}: Position #3 (RUNNER) (size: {position_per_segment}) with 500 pip distant take profit: {far_tp}")

        else:
            # For non-CFD instruments, process normally
            valid_positions = [(size, tp) for size, tp in zip(position_sizes, parsed_signal['take_profits']) if
                               size > 0]

            if not valid_positions:
                logger.warning(f"{colored_time}: No valid positions to place orders for")
                return None

            logger.info(f"{colored_time}: Processing {len(valid_positions)} positions with non-zero size")

            # Process each position
            for i, (position_size, take_profit) in enumerate(valid_positions):
                order = {
                    'instrument': instrument_data,
                    'quantity': position_size,
                    'side': parsed_signal['order_type'],
                    'order_type': order_type,
                    'price': parsed_signal['entry_point'] if order_type == 'limit' else None,
                    'stop_loss': parsed_signal['stop_loss'],
                    'take_profit': take_profit
                }
                orders_batch.append(order)

        # Place orders in parallel
        logger.info(
            f"{colored_time}: Placing {len(orders_batch)} {Fore.CYAN}{order_type.upper()}{Style.RESET_ALL} orders in parallel...")

        result = await orders_client.place_orders_batch_async(
            selected_account['id'],
            selected_account['accNum'],
            orders_batch
        )

        if result:
            # Log results
            successful_orders = result.get('successful', [])
            for j, (order, response) in enumerate(successful_orders):
                entry_point = parsed_signal['entry_point']
                stop_loss = parsed_signal['stop_loss']
                side = parsed_signal['order_type'].upper()

                # Get take profit for this specific order
                take_profit = order.get('take_profit', 'N/A')

                logger.info(
                    f"{colored_time}: {Fore.GREEN}{order_type.upper()} order placed successfully{Style.RESET_ALL} - "
                    f"Instrument: {Fore.YELLOW}{instrument_data['name']}{Style.RESET_ALL}, "
                    f"Side: {Fore.BLUE}{side}{Style.RESET_ALL}, "
                    f"Size: {Fore.YELLOW}{order.get('quantity')}{Style.RESET_ALL}, "
                    f"Entry: {Fore.YELLOW}{entry_point}{Style.RESET_ALL}, "
                    f"SL: {Fore.RED}{stop_loss}{Style.RESET_ALL}, "
                    f"TP: {Fore.GREEN}{take_profit}{Style.RESET_ALL}"
                )

                # Check for runner position to log additional info (for CFD only)
                if is_cfd and j == len(successful_orders) - 1:
                    # Extract position ID if available
                    position_id = None
                    try:
                        if isinstance(response, dict):
                            if 'd' in response and 'orderId' in response.get('d', {}):
                                position_id = response['d']['orderId']
                            elif 'orderId' in response:
                                position_id = response['orderId']
                    except Exception:
                        pass

                    logger.info(
                        f"{colored_time}: {Fore.MAGENTA}CFD Runner position{Style.RESET_ALL} (ID: {position_id}) created - "
                        f"Position monitor will handle trailing stop")

            for order, error in result.get('failed', []):
                logger.error(f"{colored_time}: {Fore.RED}Failed to place order{Style.RESET_ALL}: {error}")

            return result
        else:
            logger.error(f"{colored_time}: Failed to place orders batch.")
            return None

    except Exception as e:
        logger.error(f"{colored_time}: Error placing orders: {e}", exc_info=True)
        return None