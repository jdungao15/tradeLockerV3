import asyncio
import requests
from tradelocker_api.quotes import TradeLockerQuotes
from tradelocker_api.accounts import TradeLockerAccounts
from tradelocker_api.instruments import TradeLockerInstruments

# Pass the accounts_client, instruments_client, and quotes_client from main.py
async def monitor_existing_position(accounts_client, instruments_client, quotes_client, selected_account, base_url, auth_token):
    """
    Function to check and monitor any existing open positions every 1 second.
    """
    account_id = selected_account['id']
    acc_num = selected_account['accNum']

    while True:
        print("Checking for open positions...")

        try:
            # Get the current open positions for the account
            open_positions = accounts_client.get_current_position(account_id, acc_num)

            if open_positions and open_positions.get('d', {}).get('positions'):
                # Monitor all open positions
                for position_data in open_positions['d']['positions']:
                    monitor_position(position_data, instruments_client, quotes_client, selected_account, base_url, auth_token)

                    # Add a 1 second delay between monitoring each position to prevent overloading API requests
                    await asyncio.sleep(1)
            else:
                print("No open positions found.")

        except requests.exceptions.RequestException as e:
            print(f"Error fetching open positions: {e}")

        # Sleep for 1 second before checking again
        await asyncio.sleep(5)


def monitor_position(position_data, instruments_client, quotes_client, selected_account, base_url, auth_token):
    """
    Logic to monitor an open position, fetch live quotes, and update stop loss if needed.
    """
    position_id = position_data[0]  # Position ID
    instrument_id = position_data[1]  # Instrument ID
    route_id = position_data[2]  # Route ID
    entry_price = float(position_data[5])  # Entry price
    side = position_data[3]  # Buy or Sell side ('buy' or 'sell')

    # Fetch instrument data by instrument ID
    instrument_data = instruments_client.get_instrument_by_id(
        selected_account['id'], selected_account['accNum'], instrument_id
    )

    if not instrument_data:
        print(f"Instrument data for ID {instrument_id} not found.")
        return

    instrument_name = instrument_data['name']  # Name of the instrument

    # Fetch real-time quote for the instrument
    real_time_quote = quotes_client.get_quote(selected_account, instrument_name)

    if real_time_quote and 'd' in real_time_quote:
        ask_price = real_time_quote['d'].get('ap', 0)
        bid_price = real_time_quote['d'].get('bp', 0)

        # For a 'buy' position, the current price is the ask price.
        # For a 'sell' position, the current price is the bid price.
        current_price = ask_price if side == 'buy' else bid_price

        # Calculate pip difference
        pip_difference = calculate_pip_difference(entry_price, current_price, instrument_name)

        # Update stop loss based on buy or sell side and pip movement
        if side == 'buy' and current_price > entry_price and pip_difference >= 40:
            # For a 'buy' position, stop loss is moved up as price increases
            print(f"Price has moved {pip_difference} pips in favor (buy). Updating stop loss to break even.")
            update_stop_loss(base_url, auth_token, selected_account['accNum'], position_id, entry_price)
        elif side == 'sell' and current_price < entry_price and pip_difference >= 40:
            # For a 'sell' position, stop loss is moved down as price decreases
            print(f"Price has moved {pip_difference} pips in favor (sell). Updating stop loss to break even.")
            update_stop_loss(base_url, auth_token, selected_account['accNum'], position_id, entry_price)
        else:
            print(f"Price has not moved significantly ({pip_difference} pips). No stop loss update needed.")


def calculate_pip_difference(entry_price, current_price, instrument_name):
    """
    Calculate pip difference based on the instrument type.
    """
    if instrument_name.endswith("JPY"):
        return round(abs(current_price - entry_price) / 0.01)
    elif instrument_name == "XAUUSD":  # For example, Gold
        return round(abs(current_price - entry_price) / 0.1)
    else:
        return round(abs(current_price - entry_price) / 0.0001)


def update_stop_loss(base_url, auth_token, acc_num, position_id, new_stop_loss_price):
    """
    Function to update the stop loss for a given position using the provided API.
    """
    url = f"{base_url}/trade/positions/{position_id}"  # Endpoint for updating the position
    headers = {
        "Authorization": f"Bearer {auth_token}",  # Use the access token for authentication
        "accNum": str(acc_num),  # Account number required by the API
        "Content-Type": "application/json"  # Ensure the content type is JSON
    }

    # Body of the PATCH request to update stop loss
    body = {
        "stopLoss": new_stop_loss_price  # Set the new stop loss price
    }

    try:
        # Send PATCH request to modify the position
        response = requests.patch(url, headers=headers, json=body)
        response.raise_for_status()  # Raise an exception for 4xx/5xx errors

        # Print success message
        print(f"Stop loss updated successfully for position {position_id}. New stop loss: {new_stop_loss_price}")
        return response.json()  # Return the API response (optional)
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except Exception as err:
        print(f"Error occurred: {err}")
    return None
