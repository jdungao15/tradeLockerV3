from telethon import TelegramClient, events
from dotenv import load_dotenv
import os
from signal_parser import parse_signal
import pytz
from colorama import init, Fore, Style
from tabulate import tabulate
from risk_management import calculate_position_size
# Import from tradelocker_api package
from tradelocker_api.accounts import TradeLockerAccounts
from tradelocker_api.auth import TradeLockerAuth
from tradelocker_api.instruments import TradeLockerInstruments
from tradelocker_api.orders import TradeLockerOrders
from drawdown_manager import (
    load_drawdown_data,
    save_drawdown_data,
    reset_daily_drawdown,
    schedule_daily_reset,
    max_drawdown_balance
)
from economic_api.scraper import ensure_economic_data_exists  # Ensure scraper is imported

# Initialize colorama
init(autoreset=True)

load_dotenv()

# Replace with your own API ID and Hash
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
# Choose a session name (it will create a session file like 'my_session.session')
client = TelegramClient('my_session', int(api_id), api_hash)

# Define your local timezone
local_timezone = pytz.timezone('America/New_York')  # Replace with your timezone

# Declare as global so they can be accessed in the handler
selected_account = None
accounts_client = None


def display_accounts(auth):
    # Fetch accounts using the TradeLockerAccounts class
    accounts_client = TradeLockerAccounts(auth)
    accounts_data = accounts_client.get_accounts()

    if accounts_data:
        # Filter the account data to only show required fields and sort by account number in descending order
        account_table = []
        for account in accounts_data.get('accounts', []):
            account_table.append([account['id'], account['accNum'], account['currency'], account['accountBalance']])

        # Sort by account number in descending order
        account_table.sort(key=lambda x: int(x[1]), reverse=True)

        # Display the account data in a table format
        print(tabulate(account_table, headers=["ID", "Account Number", "Currency", "Amount"], tablefmt="fancy_grid"))
    else:
        print("No accounts available.")
    return accounts_data


async def main():
    global selected_account, accounts_client

    print("Connecting...")
    await client.start()

    # Authenticate to TradeLocker and fetch accounts
    auth = TradeLockerAuth()  # Assuming TradeLockerAuth handles your authentication
    auth.authenticate()

    # Pass the `auth` instance to other clients
    accounts_client = TradeLockerAccounts(auth)
    instruments_client = TradeLockerInstruments(auth)
    orders_client = TradeLockerOrders(auth)

    # Display accounts and ask the user to type in the account ID
    accounts_data = display_accounts(auth)

    if not accounts_data:
        print("No accounts found. Exiting.")
        return

    # Prompt user to type in the account ID
    account_id = input("Please enter the Account Number you want to use for trading: ").strip()
    selected_account = next((account for account in accounts_data['accounts'] if account['accNum'] == account_id), None)

    if selected_account:
        accounts_client.set_selected_account(selected_account)
        print(
            f"Selected account:\nID: {selected_account['id']}, Account Number: {selected_account['accNum']}, Balance: {selected_account['accountBalance']}\n")
    else:
        print(f"Account ID {account_id} is not valid. Exiting.")
        return

    # Load previous drawdown data with the selected account
    load_drawdown_data(selected_account)

    # Schedule daily drawdown reset
    schedule_daily_reset(selected_account)

    # Check if economic events JSON needs to be updated
    ensure_economic_data_exists()

    # List of channels to monitor
    print("Monitoring...")
    #-1002026354916 Millionaire clubs
    channel_ids = [-1002153475473, -1001151289381]

    @client.on(events.NewMessage(chats=channel_ids))
    async def handler(event):
        global selected_account, accounts_client

        message_text = event.message.message
        message_time_utc = event.message.date  # UTC timestamp of the message

        # Convert the UTC time to your local time zone
        message_time_local = message_time_utc.astimezone(local_timezone)
        formatted_time = message_time_local.strftime('%Y-%m-%d %H:%M:%S')
        colored_time = f"{Fore.CYAN}[{formatted_time}]{Style.RESET_ALL}"

        try:
            # Parsing Signal from Channel
            parsed_signal = parse_signal(message_text)
            if parsed_signal is None:
                print(f"{colored_time} Received invalid signal: {message_text}")
                return

            print(f"{colored_time} Received message: {message_text}")
            print(f"Using account ID: {selected_account['id']}")
            print(f"{colored_time}: Parsed signal: {parsed_signal}")

            # Fetch the latest balance from the account before proceeding
            selected_account = accounts_client.get_selected_account()
            latest_balance = float(selected_account['accountBalance'])

            # Get the instrument details
            instrument_data = instruments_client.get_instrument_by_name(
                selected_account['id'],
                selected_account['accNum'],
                parsed_signal['instrument']
            )

            if not instrument_data:
                print(f"{colored_time}: Instrument {parsed_signal['instrument']} not found. Skipping this signal.")
                return

            # Calculate position sizes
            position_sizes, risk_amount = calculate_position_size(
                instrument_data,
                parsed_signal['entry_point'],
                parsed_signal['stop_loss'],
                parsed_signal['take_profits'],
                selected_account
            )

            print(f"{colored_time}: Position sizes: {position_sizes}")
            if latest_balance - risk_amount < max_drawdown_balance:
                print(
                    f"{colored_time}: Balance {latest_balance} has reached or exceeded max drawdown balance {max_drawdown_balance}. Skipping further trades.")
                return

            # Loop over position sizes and take profits to place orders
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

                print("Placing order...")
                order_response = orders_client.create_order(**order_params)
                if order_response:
                    print(f"{colored_time}: Order placed successfully: {order_response}")
                else:
                    print("Failed to place order.")

        except KeyError as e:
            print(f"{colored_time}: Error processing signal: Missing key {e}. Skipping this signal.")
        except Exception as e:
            print(f"{colored_time}: Unexpected error: {e}. Skipping this signal.")

    await client.run_until_disconnected()


with client:
    client.loop.run_until_complete(main())
