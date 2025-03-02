import asyncio
import logging
import os
import pytz
import platform
import signal
import sys
from colorama import init, Fore, Style
from tabulate import tabulate
from dotenv import load_dotenv
from telethon import TelegramClient, events
from datetime import datetime
from cli.banner import display_banner
from cli.display_menu import display_menu
# Import our modules
from core.signal_parser import parse_signal_async
from core.risk_management import calculate_position_size
from tradelocker_api.endpoints.auth import TradeLockerAuth
from tradelocker_api.endpoints.accounts import TradeLockerAccounts
from tradelocker_api.endpoints.instruments import TradeLockerInstruments
from tradelocker_api.endpoints.orders import TradeLockerOrders
from tradelocker_api.endpoints.quotes import TradeLockerQuotes
from services.drawdown_manager import (
    load_drawdown_data,
    schedule_daily_reset,
    max_drawdown_balance
)
from services.order_handler import place_orders_with_risk_check
from services.pos_monitor import monitor_existing_position
from services.news_filter import NewsEventFilter
class TradingBot:
    def __init__(self):
        # Initialize colorama
        init(autoreset=True)

        # Set up logging
        self._setup_logging()

        # Load configuration
        self._load_config()

        # Initialize news filter
        self.news_filter = NewsEventFilter(timezone=self.local_timezone.zone)
        self.enable_news_filter = os.getenv('ENABLE_NEWS_FILTER', 'true').lower() == 'true'

        # Initialize clients as None
        self.client = None
        self.auth = None
        self.accounts_client = None
        self.instruments_client = None
        self.orders_client = None
        self.quotes_client = None
        self.selected_account = None

        # Tasks tracking
        self._tasks = set()
        self._shutdown_flag = False

    def _setup_logging(self):
        """Configure logging for the application"""
        from logging_config import setup_logging
        setup_logging()
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

        # Additional configurable parameters
        self.polling_interval = int(os.getenv('POLLING_INTERVAL', '5'))  # seconds
        self.enable_monitor = os.getenv('ENABLE_POSITION_MONITOR', 'true').lower() == 'true'
        self.enable_signals = os.getenv('ENABLE_SIGNAL_PROCESSING', 'true').lower() == 'true'

    async def initialize(self):
        """Initialize and connect to all required services"""
        try:
            # Initialize Telegram client
            self.logger.info("Connecting to Telegram...")
            self.client = TelegramClient('./my_session', int(self.api_id), self.api_hash)
            await self.client.start()

            # Authenticate with TradeLocker API
            self.auth = TradeLockerAuth()
            await self.auth.authenticate_async()

            if not await self.auth.get_access_token_async():
                self.logger.error("Failed to authenticate with TradeLocker API")
                return False

            # Initialize API clients
            self.accounts_client = TradeLockerAccounts(self.auth)
            self.instruments_client = TradeLockerInstruments(self.auth)
            self.orders_client = TradeLockerOrders(self.auth)
            self.quotes_client = TradeLockerQuotes(self.auth)

            # Initialize news filter
            if self.enable_news_filter:
                self.logger.info("Initializing economic calendar for news filtering...")
                await self.news_filter.initialize()
                # Schedule regular updates
                self._schedule_news_calendar_updates()

            return True
        except Exception as e:
            self.logger.error(f"Initialization error: {e}", exc_info=True)
            return False

    def _schedule_news_calendar_updates(self):
        """Schedule regular updates for the economic calendar"""

        async def update_calendar_task():
            while not self._shutdown_flag:
                try:
                    await asyncio.sleep(6 * 3600)  # Update every 6 hours
                    await self.news_filter.update_calendar()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Error updating economic calendar: {e}")
                    await asyncio.sleep(1800)  # Retry in 30 minutes

        task = asyncio.create_task(update_calendar_task())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def display_accounts(self):
        """Fetch and display all available accounts"""
        try:
            accounts_data = await self.accounts_client.get_accounts_async()

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
            self.logger.error(f"Error fetching accounts: {e}", exc_info=True)
            return None

    async def select_account(self, accounts_data):
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
            self.logger.error(f"Error selecting account: {e}", exc_info=True)
            return False

    async def setup_telegram_handler(self):
        """Set up the Telegram message handler"""
        if not self.enable_signals:
            self.logger.info("Signal processing is disabled. Skipping Telegram handler setup.")
            return

        @self.client.on(events.NewMessage(chats=self.channel_ids))
        async def handler(event):
            if self._shutdown_flag:
                return

            message_text = event.message.message
            message_time_utc = event.message.date

            # Convert the UTC time to local time zone
            message_time_local = message_time_utc.astimezone(self.local_timezone)
            formatted_time = message_time_local.strftime('%Y-%m-%d %H:%M:%S')
            colored_time = f"{Fore.CYAN}[{formatted_time}]{Style.RESET_ALL}"

            # Process the message in a new task to avoid blocking
            task = asyncio.create_task(self.process_message(message_text, colored_time))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def process_message(self, message_text, colored_time):
        """Process a received Telegram message"""
        try:
            # Parse signal from Telegram message
            parsed_signal = await parse_signal_async(message_text)
            if parsed_signal is None:
                self.logger.info(f"{colored_time} Received invalid signal: {message_text}")
                return

            self.logger.info(f"{colored_time} Received message: {message_text}")
            self.logger.info(f"Using account ID: {self.selected_account['id']}")

            # Check news restrictions if enabled
            if self.enable_news_filter:
                current_time = datetime.now(pytz.UTC)
                can_trade, reason = self.news_filter.can_place_order(parsed_signal, current_time)

                if not can_trade:
                    self.logger.warning(
                        f"{colored_time}: Cannot place trade for {parsed_signal['instrument']}: {reason}")
                    return

            # Refresh account data to get latest balance
            self.selected_account = await self.accounts_client.refresh_account_balance_async() or self.selected_account
            latest_balance = float(self.selected_account['accountBalance'])

            # Get instrument details
            instrument_data = await self.instruments_client.get_instrument_by_name_async(
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

            # Place the order with risk checks
            await place_orders_with_risk_check(
                self.orders_client,
                self.accounts_client,
                self.selected_account,
                instrument_data,
                parsed_signal,
                position_sizes,
                risk_amount,
                max_drawdown_balance,
                colored_time
            )

        except KeyError as e:
            self.logger.error(f"{colored_time}: Error processing signal: Missing key {e}. Skipping this signal.")
        except Exception as e:
            self.logger.error(f"{colored_time}: Unexpected error: {e}. Skipping this signal.", exc_info=True)

    async def start_position_monitoring(self):
        """Start monitoring existing positions in the background"""
        if not self.enable_monitor:
            self.logger.info("Position monitoring is disabled. Skipping monitor start.")
            return None

        self.logger.info("Starting position monitoring...")
        auth_token = await self.auth.get_access_token_async()
        monitor_task = asyncio.create_task(
            monitor_existing_position(
                self.accounts_client,
                self.instruments_client,
                self.quotes_client,
                self.selected_account,
                self.base_url,
                auth_token
            )
        )
        self._tasks.add(monitor_task)
        return monitor_task

    async def display_upcoming_news(self):
        """Display upcoming high-impact news events"""
        if not self.enable_news_filter:
            self.logger.info("News filter is disabled.")
            return

        upcoming_events = self.news_filter.get_upcoming_high_impact_events(hours=24)

        if not upcoming_events:
            self.logger.info("No upcoming high-impact news events in the next 24 hours.")
            return

        self.logger.info("Upcoming high-impact news events (next 24 hours):")
        for event in upcoming_events:
            event_time = event['datetime']
            local_time = event_time.astimezone(self.local_timezone)
            self.logger.info(f"[{local_time.strftime('%Y-%m-%d %H:%M')}] {event['currency']} - {event['event']}")

    async def cleanup(self):
        """Cleanup resources on shutdown"""
        self.logger.info("Performing cleanup...")

        # Set shutdown flag
        self._shutdown_flag = True

        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Close API clients
        if self.auth:
            await self.auth.close()

        if hasattr(self.accounts_client, 'close') and self.accounts_client:
            await self.accounts_client.close()

        if hasattr(self.instruments_client, 'close') and self.instruments_client:
            await self.instruments_client.close()

        if hasattr(self.orders_client, 'close') and self.orders_client:
            await self.orders_client.close()

        if hasattr(self.quotes_client, 'close') and self.quotes_client:
            await self.quotes_client.close()

        # Disconnect Telegram client
        if self.client:
            await self.client.disconnect()

        self.logger.info("Cleanup completed.")

    async def run(self):
        """Main execution method"""

        try:

            # Initialize connections and authenticate
            if not await self.initialize():
                self.logger.error("Initialization failed. Exiting.")
                return

            # Display and select account
            accounts_data = await self.display_accounts()
            if not accounts_data:
                self.logger.error("No accounts found. Exiting.")
                return

            if not await self.select_account(accounts_data):
                self.logger.error("Account selection failed. Exiting.")
                return

            # Load drawdown data and schedule daily reset
            load_drawdown_data(self.selected_account)
            schedule_daily_reset(self.selected_account)

            # Set up message handler
            await self.setup_telegram_handler()

            # Display upcoming news events
            if self.enable_news_filter:
                await self.display_upcoming_news()

            # Start monitoring existing positions
            monitoring_task = await self.start_position_monitoring()
            if monitoring_task:
                self._tasks.add(monitoring_task)

            # Run until disconnected or interrupted
            self.logger.info("Bot is now running. Press Ctrl+C to stop.")
            await self.client.run_until_disconnected()

        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt. Shutting down...")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            await self.cleanup()


async def shutdown(loop):
    """Handle graceful shutdown when CTRL+C is pressed"""
    logging.info("Shutdown signal received. Closing all connections...")

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()
    logging.info("Shutdown complete.")


async def main():
    """Main entry point with Windows-compatible signal handling"""
    # Display banner first
    display_banner()

    # Show menu and get choice
    choice = display_menu()

    if choice == '2':
        print(f"{Fore.YELLOW}Exiting program. Goodbye!{Style.RESET_ALL}")
        return

    elif choice == '1':
        bot = TradingBot()

        # Set up signal handlers for systems that support them (Unix/Linux/Mac)
        if platform.system() != "Windows":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(loop)))

        # Run the bot
        await bot.run()

    else:
        print(f"{Fore.RED}Invalid choice. Exiting.{Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        # On Windows, we rely on KeyboardInterrupt exception instead of signals
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
    except Exception as e:
        logging.error(f"Critical error: {e}", exc_info=True)
        sys.exit(1)