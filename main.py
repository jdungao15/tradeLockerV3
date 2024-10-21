import asyncio
from telethon import TelegramClient, events
from dotenv import load_dotenv
from economic_api.economic_calendar import check_economic_events
from signal_parser import parse_signal
import os
import pytz
from colorama import init, Fore, Style
from tabulate import tabulate
from risk_management import calculate_position_size
from tradelocker_api.accounts import TradeLockerAccounts
from tradelocker_api.auth import TradeLockerAuth
from tradelocker_api.instruments import TradeLockerInstruments
from tradelocker_api.orders import TradeLockerOrders
from tradelocker_api.quotes import TradeLockerQuotes
from drawdown_manager import (
    load_drawdown_data,
    schedule_daily_reset,
    max_drawdown_balance
)
from order_handler import place_order
from pos_monitor import monitor_existing_position  # Import the position monitor
from economic_api.scraper import ensure_economic_data_exists  # Import economic event checker

# Initialize colorama
init(autoreset=True)

# Load environment variables
load_dotenv()

# Replace with your own API ID and Hash
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
client = TelegramClient('my_session', int(api_id), api_hash)
local_timezone = pytz.timezone('America/New_York')

selected_account = None
accounts_client = None
base_url = os.getenv('TRADELOCKER_API_URL')  # Replace with your API base URL


def display_accounts(auth):
    """
    Fetch and display all available accounts using the TradeLocker API.
    """
    global accounts_client
    accounts_client = TradeLockerAccounts(auth)
    accounts_data = accounts_client.get_accounts()

    if accounts_data:
        account_table = [
            [account['id'], account['accNum'], account['currency'], account['accountBalance']]
            for account in accounts_data.get('accounts', [])
        ]
        account_table.sort(key=lambda x: int(x[1]), reverse=True)
        print(tabulate(account_table, headers=["ID", "Account Number", "Currency", "Amount"], tablefmt="fancy_grid"))
    else:
        print("No accounts available.")
    return accounts_data


async def main():
    global selected_account, accounts_client, base_url

    print("Connecting to Telegram...")
    await client.start()

    # Authenticate with the TradeLocker API
    auth = TradeLockerAuth()
    auth.authenticate()
    auth_token = auth.get_access_token()  # Get the auth token to pass along

    accounts_client = TradeLockerAccounts(auth)
    instruments_client = TradeLockerInstruments(auth)
    orders_client = TradeLockerOrders(auth)
    quotes_client = TradeLockerQuotes(auth)  # Initialize quotes client

    # Fetch and display available accounts
    accounts_data = display_accounts(auth)

    if not accounts_data:
        print("No accounts found. Exiting.")
        return

    account_id = input("Please enter the Account Number you want to use for trading: ").strip()
    selected_account = next((account for account in accounts_data['accounts'] if account['accNum'] == account_id), None)

    if selected_account:
        accounts_client.set_selected_account(selected_account)
        print(f"Selected account:\nID: {selected_account['id']}, Account Number: {selected_account['accNum']}, "
              f"Balance: {selected_account['accountBalance']}\n")
    else:
        print(f"Account ID {account_id} is not valid. Exiting.")
        return

    # Load drawdown data and schedule daily reset
    load_drawdown_data(selected_account)
    schedule_daily_reset(selected_account)
    ensure_economic_data_exists()

    # Start monitoring existing positions in the background
    asyncio.create_task(
        monitor_existing_position(accounts_client, instruments_client, quotes_client, selected_account, base_url, auth_token)
    )

    # Monitor Telegram channels for signals
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
            # Parse signal from Telegram message
            parsed_signal = parse_signal(message_text)
            if parsed_signal is None:
                print(f"{colored_time} Received invalid signal: {message_text}")
                return

            print(f"{colored_time} Received message: {message_text}")
            print(f"Using account ID: {selected_account['id']}")
            print(f"{colored_time}: Parsed signal: {parsed_signal}")

            # Fetch the latest balance from the account
            selected_account = accounts_client.get_selected_account()
            latest_balance = float(selected_account['accountBalance'])

            # Get instrument details for the trade
            instrument_data = instruments_client.get_instrument_by_name(
                selected_account['id'],
                selected_account['accNum'],
                parsed_signal['instrument']
            )

            if not instrument_data:
                print(f"{colored_time}: Instrument {parsed_signal['instrument']} not found. Skipping this signal.")
                return

            # Check if there are any high impact economic events for the instrument
            instrument_currency = parsed_signal['instrument'][-3:]
            high_impact_events = check_economic_events(instrument_currency, message_time_local)

            if high_impact_events:
                print(f"{colored_time}: High impact event detected for {instrument_currency}. Skipping trade.")
                return

            # Calculate position sizes based on risk management
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

            # Place the order
            place_order(orders_client, selected_account, instrument_data, parsed_signal, position_sizes, colored_time)

        except KeyError as e:
            print(f"{colored_time}: Error processing signal: Missing key {e}. Skipping this signal.")
        except Exception as e:
            print(f"{colored_time}: Unexpected error: {e}. Skipping this signal.")

    await client.run_until_disconnected()


with client:
    client.loop.run_until_complete(main())
