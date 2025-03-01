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


async def place_orders_with_risk_check(orders_client, accounts_client, selected_account,
                                       instrument_data, parsed_signal, position_sizes, risk_amount,
                                       max_drawdown_balance, colored_time):
    """
    Place orders with additional risk management checks

    Args:
        orders_client: Orders API client
        accounts_client: Accounts API client
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

        # Proceed with order placement
        return await place_order_async(
            orders_client, updated_account, instrument_data,
            parsed_signal, position_sizes, colored_time
        )

    except Exception as e:
        logger.error(f"{colored_time}: Error in order placement with risk check: {e}", exc_info=True)
        return None