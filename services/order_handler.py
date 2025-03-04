import logging
import asyncio
from typing import List, Dict, Any

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
            threshold_pips = 5
            if instrument_data['name'] == "DJI30":
                threshold_pips = 8  # Higher for US30 (due to +5 pips adjustment in signal_parser)

            if pip_diff <= threshold_pips:
                order_type = 'market'

                # Adjust stop loss: add diff for buy, subtract for sell
                if side == 'buy':
                    adjusted_stop_loss = parsed_signal['stop_loss'] + price_diff
                else:  # sell
                    adjusted_stop_loss = parsed_signal['stop_loss'] - price_diff

                logger.info(
                    f"{colored_time}: Using MARKET {side.upper()} instead of limit. "
                    f"Current price: {current_price}, Entry: {parsed_signal['entry_point']}, "
                    f"Diff: {pip_diff} pips, Adjusted SL: {adjusted_stop_loss}"
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

    Args:
        orders_client: Asynchronous orders client
        selected_account: Account information dictionary
        instrument_data: Instrument data dictionary
        parsed_signal: Parsed trading signal
        position_sizes: List of position sizes
        colored_time: Formatted time string for logging
        order_type: Type of order to place ('limit' or 'market')
    """
    try:
        # Prepare order batch
        orders_batch = []

        for position_size, take_profit in zip(position_sizes, parsed_signal['take_profits']):
            order = {
                'instrument': instrument_data,
                'quantity': position_size,
                'side': parsed_signal['order_type'],
                'order_type': order_type,
                'price': parsed_signal['entry_point'] if order_type == 'limit' else None,
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': take_profit,
            }
            orders_batch.append(order)

        # Place orders in parallel
        logger.info(f"{colored_time}: Placing {len(orders_batch)} {order_type} orders in parallel...")

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