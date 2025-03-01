import asyncio
import logging
import os
import pytz
from colorama import init, Fore, Style
from tabulate import tabulate
from dotenv import load_dotenv
from telethon import TelegramClient, events

from signal_parser import parse_signal
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
from pos_monitor import monitor_existing_position


class TradingBot:
    def __init__(self):
        # Initialize colorama
        init(autoreset=True)

        # Set up logging
        self._setup_logging()

        # Load configuration
        self._load_config()

        # Initialize clients as None
        self.client = None
        self.auth = None
        self.accounts_client = None
        self.instruments_client = None
        self.orders_client = None
        self.quotes_client = None
        self.selected_account = None

    def _setup_logging(self):
        """Configure logging for the application"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("trading_bot.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("trading_bot")

    def _load_config(self):
        """Load environment variables and configuration"""
        load_dotenv()

        # Check for required environment variables
        required_vars = ['API_ID', 'API_HASH', 'TRADELOCKER_API_URL']
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            self.logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

        self.api_id = os.getenv('API_ID')
        self.api_hash = os.getenv('API_HASH')
        self.base_url = os.getenv('TRADELOCKER_API_URL')

        # Configuration that could be moved to a config file
        self.channel_ids = [-1002153475473, -1001151289381, -1002486712356]
        self.local_timezone = pytz.timezone('America/New_York')

    async def initialize(self):
        """Initialize and connect to all required services"""
        try:
            # Initialize Telegram client
            self.logger.info("Connecting to Telegram...")
            self.client = TelegramClient('my_session', int(self.api_id), self.api_hash)
            await self.client.start()

            # Authenticate with TradeLocker API
            self.auth = TradeLockerAuth()
            self.auth.authenticate()

            if not self.auth.get_access_token():
                self.logger.error("Failed to authenticate with TradeLocker API")
                return False

            # Initialize API clients
            self.accounts_client = TradeLockerAccounts(self.auth)
            self.instruments_client = TradeLockerInstruments(self.auth)
            self.orders_client = TradeLockerOrders(self.auth)
            self.quotes_client = TradeLockerQuotes(self.auth)

            return True
        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return False

    def display_accounts(self):
        """Fetch and display all available accounts"""
        try:
            accounts_data = self.accounts_client.get_accounts()

            if not accounts_data or not accounts_data.get('accounts'):
                self.logger.info("No accounts available.")
                return None

            account_table = [
                [account['id'], account['accNum'], account['currency'], account['accountBalance']]
                for account in accounts_data.get('accounts', [])
            ]
            account_table.sort(key=lambda x: int(x[1]), reverse=True)

            print(
                tabulate(account_table, headers=["ID", "Account Number", "Currency", "Amount"], tablefmt="fancy_grid"))
            return accounts_data
        except Exception as e:
            self.logger.error(f"Error fetching accounts: {e}")
            return None

    def select_account(self, accounts_data):
        """Prompt user to select an account to use for trading"""
        try:
            account_id = input("Please enter the Account Number you want to use for trading: ").strip()
            selected_account = next(
                (account for account in accounts_data['accounts'] if account['accNum'] == account_id),
                None
            )

            if selected_account:
                self.accounts_client.set_selected_account(selected_account)
                self.selected_account = selected_account
                self.logger.info(
                    f"Selected account: ID: {selected_account['id']}, "
                    f"Account Number: {selected_account['accNum']}, "
                    f"Balance: {selected_account['accountBalance']}"
                )
                return True
            else:
                self.logger.error(f"Account ID {account_id} is not valid.")
                return False
        except Exception as e:
            self.logger.error(f"Error selecting account: {e}")
            return False

    async def setup_telegram_handler(self):
        """Set up the Telegram message handler"""

        @self.client.on(events.NewMessage(chats=self.channel_ids))
        async def handler(event):
            message_text = event.message.message
            message_time_utc = event.message.date

            # Convert the UTC time to local time zone
            message_time_local = message_time_utc.astimezone(self.local_timezone)
            formatted_time = message_time_local.strftime('%Y-%m-%d %H:%M:%S')
            colored_time = f"{Fore.CYAN}[{formatted_time}]{Style.RESET_ALL}"

            await self.process_message(message_text, colored_time)

    async def process_message(self, message_text, colored_time):
        """Process a received Telegram message"""
        try:
            # Parse signal from Telegram message
            parsed_signal = parse_signal(message_text)
            if parsed_signal is None:
                self.logger.info(f"{colored_time} Received invalid signal: {message_text}")
                return

            self.logger.info(f"{colored_time} Received message: {message_text}")
            self.logger.info(f"Using account ID: {self.selected_account['id']}")

            # Refresh account data to get latest balance
            self.selected_account = self.accounts_client.get_selected_account()
            latest_balance = float(self.selected_account['accountBalance'])

            # Get instrument details
            instrument_data = self.instruments_client.get_instrument_by_name(
                self.selected_account['id'],
                self.selected_account['accNum'],
                parsed_signal['instrument']
            )

            if not instrument_data:
                self.logger.warning(
                    f"{colored_time}: Instrument {parsed_signal['instrument']} not found. Skipping this signal."
                )
                return

            # Calculate position sizes based on risk management
            position_sizes, risk_amount = calculate_position_size(
                instrument_data,
                parsed_signal['entry_point'],
                parsed_signal['stop_loss'],
                parsed_signal['take_profits'],
                self.selected_account
            )

            self.logger.info(f"{colored_time}: Position sizes: {position_sizes}")

            # Check drawdown limits
            if latest_balance - risk_amount < max_drawdown_balance:
                self.logger.warning(
                    f"{colored_time}: Balance {latest_balance} has reached or exceeded "
                    f"max draw down balance {max_drawdown_balance}. Skipping further trades."
                )
                return

            # Place the order
            place_order(
                self.orders_client,
                self.selected_account,
                instrument_data,
                parsed_signal,
                position_sizes,
                colored_time
            )

        except KeyError as e:
            self.logger.error(f"{colored_time}: Error processing signal: Missing key {e}. Skipping this signal.")
        except Exception as e:
            self.logger.error(f"{colored_time}: Unexpected error: {e}. Skipping this signal.")

    async def start_position_monitoring(self):
        """Start monitoring existing positions in the background"""
        auth_token = self.auth.get_access_token()
        return asyncio.create_task(
            monitor_existing_position(
                self.accounts_client,
                self.instruments_client,
                self.quotes_client,
                self.selected_account,
                self.base_url,
                auth_token
            )
        )

    async def run(self):
        """Main execution method"""
        # Initialize connections and authenticate
        if not await self.initialize():
            self.logger.error("Initialization failed. Exiting.")
            return

        # Display and select account
        accounts_data = self.display_accounts()
        if not accounts_data:
            self.logger.error("No accounts found. Exiting.")
            return

        if not self.select_account(accounts_data):
            self.logger.error("Account selection failed. Exiting.")
            return

        # Load drawdown data and schedule daily reset
        load_drawdown_data(self.selected_account)
        schedule_daily_reset(self.selected_account)

        # Set up message handler
        await self.setup_telegram_handler()

        # Start monitoring existing positions
        monitoring_task = await self.start_position_monitoring()

        # Run until disconnected
        self.logger.info("Bot is now running. Press Ctrl+C to stop.")
        await self.client.run_until_disconnected()

        # Cleanup when disconnected
        monitoring_task.cancel()


async def main():
    bot = TradingBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())