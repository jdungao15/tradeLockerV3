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
                            colored_time, order_type='limit'):
    """
    Places orders for the given instrument and parsed signal - asynchronous version.
    """
    try:
        # Import risk config for TP selection
        import risk_config

        # Check if this is a CFD instrument (for logging purposes only)
        is_cfd = instrument_data['type'] == "EQUITY_CFD" and instrument_data['name'] != "XAUUSD"
        logger.info(f"{colored_time}: Instrument {instrument_data['name']} is {'CFD' if is_cfd else 'non-CFD/XAUUSD'}")

        # Get valid positions with non-zero size
        valid_positions = [(size, tp) for size, tp in zip(position_sizes, parsed_signal['take_profits']) if size > 0]

        if not valid_positions:
            logger.warning(f"{colored_time}: No valid positions to place orders for")
            return None

        # Get current TP selection preference
        tp_selection = risk_config.get_tp_selection()
        mode = tp_selection.get('mode', 'all')

        # Log the TP selection mode
        logger.info(f"{colored_time}: Using TP selection mode: {mode}")

        # Prepare orders batch
        orders_batch = []

        # Calculate total position size
        total_pos_size = sum(size for size, _ in valid_positions)

        # Number of positions to create equals the number of valid positions
        num_positions = len(valid_positions)

        # Equal position size distribution
        position_per_segment = round(total_pos_size / num_positions, 2)

        # Create orders for each valid position
        for i, (_, take_profit) in enumerate(valid_positions):
            order = {
                'instrument': instrument_data,
                'quantity': position_per_segment,
                'side': parsed_signal['order_type'],
                'order_type': order_type,
                'price': parsed_signal['entry_point'] if order_type == 'limit' else None,
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': take_profit
            }
            orders_batch.append(order)

            # If this is the last position and there are multiple positions, note it's a runner
            runner_note = " (RUNNER)" if i == num_positions - 1 and num_positions > 1 else ""
            logger.info(
                f"{colored_time}: Position #{i + 1}{runner_note} (size: {position_per_segment}) with take profit: {take_profit}")

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

                # Extract position ID if available and mark as runner if it's the last position
                if is_runner:
                    position_id = None
                    try:
                        if isinstance(response, dict):
                            if 'd' in response and 'orderId' in response.get('d', {}):
                                position_id = response['d']['orderId']
                            elif 'orderId' in response:
                                position_id = response['orderId']
                    except Exception:
                        pass

                    # If this is a CFD instrument and a runner, note it for position monitoring
                    if is_cfd:
                        logger.info(
                            f"{colored_time}: {Fore.MAGENTA}Runner position{Style.RESET_ALL} (ID: {position_id}) created - "
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