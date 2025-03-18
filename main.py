import asyncio
import logging
import os
import pytz
import platform
import signal
import sys
import getpass
from colorama import init, Fore, Style
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from datetime import datetime
from cli.banner import display_banner
from cli.display_menu import display_menu, display_risk_menu, get_risk_percentage_input
from core.signal_parser import parse_signal_async
from core.risk_management import calculate_position_size
from tradelocker_api.endpoints.auth import TradeLockerAuth
from tradelocker_api.endpoints.accounts import TradeLockerAccounts
from tradelocker_api.endpoints.instruments import TradeLockerInstruments
from tradelocker_api.endpoints.orders import TradeLockerOrders
from tradelocker_api.endpoints.quotes import TradeLockerQuotes
from services.drawdown_manager import (
    load_drawdown_data,
    schedule_daily_reset_async,
    max_drawdown_balance
)
from services.order_handler import place_orders_with_risk_check
from services.pos_monitor import monitor_existing_position
from services.news_filter import NewsEventFilter
from services.missed_signal_detection import MissedSignalHandler
from services.signal_management import SignalManagementHandler
import risk_config
from core.signal_parser import find_matching_instrument

class TradingBot:
    def __init__(self):
        # Initialize colorama
        init(autoreset=True)

        # Set up logging
        self._setup_logging()

        # Load configuration
        self._load_config()

        # Initialize service handlers
        self.news_filter = NewsEventFilter(timezone=self.local_timezone.zone)
        self.enable_news_filter = os.getenv('ENABLE_NEWS_FILTER', 'true').lower() == 'true'
        self.missed_signal_handler = None  # Will be initialized later
        self.signal_manager = None  # Will be initialized later

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

    # -------------------------------------------------------------------------
    # Initialization and Setup Methods
    # -------------------------------------------------------------------------

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
        self.channel_ids = [-1002153475473, -1002486712356]
        self.local_timezone = pytz.timezone('America/New_York')

        # Additional configurable parameters
        self.polling_interval = int(os.getenv('POLLING_INTERVAL', '5'))  # seconds
        self.enable_monitor = os.getenv('ENABLE_POSITION_MONITOR', 'true').lower() == 'true'
        self.enable_signals = os.getenv('ENABLE_SIGNAL_PROCESSING', 'true').lower() == 'true'

    async def initialize(self):
        """Initialize and connect to all required services"""
        try:
            # Initialize Telegram client with explicit authentication flow
            self.logger.info("Connecting to Telegram...")
            self.client = TelegramClient('./my_session', int(self.api_id), self.api_hash)

            # Connect first
            await self.client.connect()

            # Check if already authorized
            if not await self.client.is_user_authorized():
                self.logger.info("Telegram authentication required")
                phone = input("Please enter your phone (or bot token): ")
                await self.client.send_code_request(phone)
                code = input("Please enter the code you received: ")

                try:
                    # Simple sign-in without 2FA handling
                    await self.client.sign_in(phone, code)
                    self.logger.info("Telegram authentication successful")
                except Exception as e:
                    self.logger.error(f"Authentication error: {e}")
                    return False
            else:
                self.logger.info("Already authenticated with Telegram")

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

            # Initialize missed signal handler
            self.missed_signal_handler = MissedSignalHandler(
                self.accounts_client,
                self.orders_client,
                self.instruments_client,
                self.auth
            )

            # Configure the missed signal handler
            await self.configure_missed_signal_handler(
                enable_fallback=False,  # Default: Don't cancel unrelated orders
                max_signal_age_hours=48,  # Only consider signals from last 48 hours
                consider_channel=True  # Consider channel source when matching signals
            )

            # Initialize signal management handler
            self.signal_manager = SignalManagementHandler(
                self.accounts_client,
                self.orders_client,
                self.instruments_client,
                self.quotes_client,
                self.auth
            )

            # Apply current risk profile settings to signal manager
            current_profile = risk_config.detect_current_profile()
            self.signal_manager.set_risk_profile_settings(current_profile)

            # Link to the missed signal handler's history
            if self.missed_signal_handler:
                self.signal_manager.set_signal_history(self.missed_signal_handler.signal_history)

            return True
        except Exception as e:
            self.logger.error(f"Initialization error: {e}", exc_info=True)
            return False

    async def configure_missed_signal_handler(self, enable_fallback=False, max_signal_age_hours=48,
                                              consider_channel=True):
        """
        Configure the missed signal handler's behavior.

        Args:
            enable_fallback (bool): Whether to enable the fallback protection
                                  (cancelling all orders when no specific match)
            max_signal_age_hours (int): Maximum age of signals to consider for matching (hours)
            consider_channel (bool): Whether to consider channel/source when matching signals
        """
        if not self.missed_signal_handler:
            self.logger.warning("Missed signal handler not initialized yet.")
            return False

        self.missed_signal_handler.enable_fallback_protection = enable_fallback
        self.missed_signal_handler.max_signal_age_hours = max_signal_age_hours
        self.missed_signal_handler.consider_channel_source = consider_channel

        self.logger.info(
            f"Missed signal handler configured: "
            f"Fallback protection {'ENABLED' if enable_fallback else 'DISABLED'}, "
            f"Signal age limit: {max_signal_age_hours} hours, "
            f"Consider channel source: {'YES' if consider_channel else 'NO'}"
        )
        return True

    # -------------------------------------------------------------------------
    # Monitoring Methods
    # -------------------------------------------------------------------------

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

    async def start_drawdown_monitor(self):
        """Start the drawdown monitoring with proper async handling"""
        # Load drawdown data
        load_drawdown_data(self.selected_account)

        # Schedule first reset using async approach
        reset_task = asyncio.create_task(
            schedule_daily_reset_async(self.accounts_client, self.selected_account)
        )
        self._tasks.add(reset_task)
        reset_task.add_done_callback(self._tasks.discard)

    async def display_upcoming_news(self):
        """Display upcoming high-impact news events for major currencies"""
        if not self.enable_news_filter:
            self.logger.info("News filter is disabled.")
            return

        # Focus on major currencies typically traded
        major_currencies = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]

        try:
            # Use our new method to get high-impact events for major currencies
            upcoming_events = self.news_filter.get_high_impact_events_for_currencies(
                major_currencies, hours=24
            )
        except AttributeError:
            # Fall back to the old method if the new one isn't available
            upcoming_events = self.news_filter.get_upcoming_high_impact_events(hours=24)

        if not upcoming_events:
            self.logger.info("No upcoming high-impact news events in the next 24 hours.")
            return

        self.logger.info("Upcoming high-impact news events (next 24 hours):")
        for event in upcoming_events:
            event_time = event['datetime']
            local_time = event_time.astimezone(self.local_timezone)
            self.logger.info(
                f"[{local_time.strftime('%Y-%m-%d %H:%M')}] {event['currency']} - {event['event']}"
            )

    # -------------------------------------------------------------------------
    # Account Management Methods
    # -------------------------------------------------------------------------

    async def display_accounts(self):
        """Fetch and display all available accounts with colorama for reliable color output"""
        try:
            from colorama import init, Fore, Back, Style
            # Initialize colorama with autoreset and force mode
            init(autoreset=True, convert=True, strip=False, wrap=True)

            accounts_data = await self.accounts_client.get_accounts_async()

            if not accounts_data or not accounts_data.get('accounts'):
                self.logger.info("No accounts available.")
                return None

            # Sort accounts by Account Number (descending)
            accounts = sorted(accounts_data.get('accounts', []),
                              key=lambda x: int(x['accNum']), reverse=True)

            # Calculate column widths for proper alignment
            id_width = max(len("ID"), max(len(acc['id']) for acc in accounts)) + 2
            acc_width = max(len("Account Number"), max(len(acc['accNum']) for acc in accounts)) + 2
            currency_width = max(len("Currency"), max(len(acc['currency']) for acc in accounts)) + 2

            # Calculate maximum balance width
            balance_width = max(
                len("Balance"),
                max(len(f"${float(acc['accountBalance']):,.2f}") for acc in accounts),
                len(f"${sum(float(acc['accountBalance']) for acc in accounts):,.2f}")
            ) + 2

            # Calculate total width
            total_width = id_width + acc_width + currency_width + balance_width + 3  # 3 for the separators

            # Print top border and title
            print(f"\n{Fore.CYAN}{Style.BRIGHT}{'═' * total_width}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}{Style.BRIGHT}{'Available Trading Accounts':^{total_width}}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}{Style.BRIGHT}{'═' * total_width}{Style.RESET_ALL}")

            # Print header row
            print(
                f"{Fore.YELLOW}{Style.BRIGHT}{'ID':<{id_width}} │ {'Account Number':<{acc_width}} │ {'Currency':<{currency_width}} │ {'Balance':>{balance_width}}{Style.RESET_ALL}")
            print(
                f"{Fore.YELLOW}{'─' * id_width}─┼─{'─' * acc_width}─┼─{'─' * currency_width}─┼─{'─' * balance_width}{Style.RESET_ALL}")

            # Print each account row
            for i, account in enumerate(accounts):
                # Alternate row colors for better readability
                row_color = Fore.LIGHTBLUE_EX if i % 2 == 0 else Fore.WHITE

                # Format balance with currency symbol and commas
                balance = float(account['accountBalance'])
                formatted_balance = f"${balance:,.2f}"

                # Choose balance color based on amount
                if balance > 25000:
                    balance_color = Fore.GREEN
                elif balance > 10000:
                    balance_color = Fore.CYAN
                elif balance > 5000:
                    balance_color = Fore.YELLOW
                else:
                    balance_color = Fore.RED

                # Print the formatted row
                print(
                    f"{row_color}{account['id']:<{id_width}} │ {account['accNum']:<{acc_width}} │ {account['currency']:<{currency_width}} │ {balance_color}{formatted_balance:>{balance_width}}{Style.RESET_ALL}")

            # Print bottom separator
            print(
                f"{Fore.YELLOW}{'─' * id_width}─┼─{'─' * acc_width}─┼─{'─' * currency_width}─┼─{'─' * balance_width}{Style.RESET_ALL}")

            # Print summary row
            total_accounts = len(accounts)
            total_balance = sum(float(account['accountBalance']) for account in accounts)
            formatted_total = f"${total_balance:,.2f}"

            print(
                f"{Fore.GREEN}{Style.BRIGHT}{'TOTAL':<{id_width}} │ {f'{total_accounts} accounts':<{acc_width}} │ {'':^{currency_width}} │ {formatted_total:>{balance_width}}{Style.RESET_ALL}")

            # Print bottom border with timestamp
            print(f"{Fore.CYAN}{Style.BRIGHT}{'═' * total_width}{Style.RESET_ALL}")

            # Add timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"{Fore.CYAN}{'Account data as of ' + timestamp:^{total_width}}{Style.RESET_ALL}\n")

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

    # -------------------------------------------------------------------------
    # Communication Methods (Telegram)
    # -------------------------------------------------------------------------

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

            # Extract channel information
            chat = event.chat if hasattr(event, 'chat') else None
            channel_id = str(chat.id) if chat else None
            channel_name = chat.title if chat and hasattr(chat, 'title') else None

            # Extract message and reply information
            message_id = str(event.message.id) if hasattr(event.message, 'id') else None
            reply_to_msg_id = None

            # Check if this is a reply to another message
            if hasattr(event.message, 'reply_to') and event.message.reply_to:
                reply_to_msg_id = str(event.message.reply_to.reply_to_msg_id)
                self.logger.debug(f"Message is a reply to message ID: {reply_to_msg_id}")

            # Convert the UTC time to local time zone
            message_time_local = message_time_utc.astimezone(self.local_timezone)
            formatted_time = message_time_local.strftime('%Y-%m-%d %H:%M:%S')
            colored_time = f"{Fore.CYAN}[{formatted_time}]{Style.RESET_ALL}"

            # Process the message in a new task with reply information
            task = asyncio.create_task(
                self.process_message(
                    message_text,
                    colored_time,
                    event,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    reply_to_msg_id=reply_to_msg_id
                )
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    # -------------------------------------------------------------------------
    # Trading Signal Processing Methods
    # -------------------------------------------------------------------------

    async def process_message(self, message_text, colored_time, event=None, channel_id=None, channel_name=None,
                              reply_to_msg_id=None):
        """Process a received Telegram message"""
        try:
            # Extract message ID if available
            message_id = str(event.message.id) if event and hasattr(event, 'message') else None

            # First, check if this is a management instruction (move SL to BE, close early)
            if self.signal_manager:
                is_handled, result = await self.signal_manager.handle_message(
                    message_text,
                    self.selected_account,
                    colored_time,
                    reply_to_msg_id  # Pass the reply_to_msg_id
                )

                if is_handled:
                    # If it was a management instruction and we handled it, we can stop processing
                    instruction_type = result.get("instruction_type", "unknown")
                    success = result.get("success", False)
                    instrument = result.get("instrument", "unknown instrument")

                    if success:
                        self.logger.info(
                            f"{colored_time}: {Fore.GREEN}Successfully executed {instruction_type} "
                            f"instruction for {instrument}{Style.RESET_ALL}"
                        )
                    else:
                        self.logger.warning(
                            f"{colored_time}: {Fore.YELLOW}Failed to execute {instruction_type} "
                            f"instruction for {instrument}{Style.RESET_ALL}"
                        )
                    return

            # Then, check if this is a TP hit message using the missed signal handler
            if self.missed_signal_handler:
                is_handled, result = await self.missed_signal_handler.handle_message(
                    message_text,
                    self.selected_account,
                    colored_time,
                    message_id,
                    channel_id,
                    channel_name,
                    reply_to_msg_id  # Pass the reply_to_msg_id
                )

                if is_handled:
                    # If it was a TP hit message and we handled it, we can stop processing
                    if result and result.get("action") == "cancelled":
                        matched_signal = f"with signal_id {result.get('matched_signal_id')}" if result.get(
                            'matched_signal_id') else ""
                        fallback_note = " (using fallback protection)" if result.get("fallback_used") else ""
                        self.logger.warning(
                            f"{colored_time}: {Fore.RED}Cancelled {result.get('cancelled_count')} pending orders "
                            f"for {result.get('instrument')} due to missed signal (TP{result.get('tp_level')} hit) "
                            f"{matched_signal}{fallback_note}{Style.RESET_ALL}"
                        )
                    return

            # Parse signal from Telegram message
            parsed_signal = await parse_signal_async(message_text)
            if parsed_signal is None:
                self.logger.info(f"{colored_time} Received invalid signal: {message_text}")
                return

            # Store the parsed signal in history for future reference
            signal_id = None
            if self.missed_signal_handler:
                signal_id = self.missed_signal_handler.add_signal_to_history(
                    parsed_signal,
                    message_id=message_id,
                    raw_message=message_text,
                    channel_id=channel_id,
                    channel_name=channel_name
                )

            # Check if this is a reduced risk signal
            reduced_risk = parsed_signal.get('reduced_risk', False)
            if reduced_risk:
                self.logger.info(f"{colored_time} {Fore.YELLOW}Signal identified as REDUCED RISK.{Style.RESET_ALL}")

            self.logger.info(f"{colored_time} {Fore.CYAN}Received trading signal:{Style.RESET_ALL} {message_text}")
            self.logger.info(
                f"{Fore.YELLOW}Signal details:{Style.RESET_ALL} Instrument: {Fore.GREEN}{parsed_signal['instrument']}{Style.RESET_ALL}, "
                f"Type: {Fore.GREEN}{parsed_signal['order_type'].upper()}{Style.RESET_ALL}, "
                f"Entry: {Fore.CYAN}{parsed_signal['entry_point']}{Style.RESET_ALL}, "
                f"SL: {Fore.RED}{parsed_signal['stop_loss']}{Style.RESET_ALL}")
            self.logger.info(
                f"Take profits: {Fore.GREEN}{', '.join(map(str, parsed_signal['take_profits']))}{Style.RESET_ALL}")
            self.logger.info(f"Using account ID: {self.selected_account['id']}")

            # Check news restrictions if enabled
            if self.enable_news_filter:
                current_time = datetime.now(pytz.UTC)
                try:
                    can_trade, reason = self.news_filter.can_place_order(parsed_signal, current_time)

                    if not can_trade:
                        self.logger.warning(
                            f"{colored_time}: {Fore.RED}Cannot place trade for {parsed_signal['instrument']}: {reason}{Style.RESET_ALL}")
                        return
                except AttributeError as e:
                    # Handle the case where the method might not be available
                    self.logger.error(f"{colored_time}: Unexpected error: {e}. Skipping this signal.")
                    return

            # Refresh account data to get latest balance
            self.selected_account = await self.accounts_client.refresh_account_balance_async() or self.selected_account
            latest_balance = float(self.selected_account['accountBalance'])

            # Get instrument details
            instrument_data = await find_matching_instrument(
                self.instruments_client,
                self.selected_account,
                parsed_signal
            )

            if not instrument_data:
                self.logger.warning(
                    f"{colored_time}: {Fore.RED}Instrument {parsed_signal['instrument']} not found. Skipping this signal.{Style.RESET_ALL}"
                )
                return

            # Calculate position sizes based on risk management, passing the reduced_risk flag
            position_sizes, risk_amount = calculate_position_size(
                instrument_data,
                parsed_signal['entry_point'],
                parsed_signal['stop_loss'],
                parsed_signal['take_profits'],
                self.selected_account,
                reduced_risk  # Pass the reduced risk flag
            )

            self.logger.info(f"{colored_time}: Position sizes: {Fore.YELLOW}{position_sizes}{Style.RESET_ALL}")

            # Display risk information
            risk_percentage = "0.75%" if reduced_risk else "1.5%"  # Approximate values for display
            self.logger.info(f"{colored_time}: {Fore.CYAN}Risk percentage: {risk_percentage} " +
                             f"({Fore.RED}REDUCED{Style.RESET_ALL} due to signal keywords)" if reduced_risk else "")

            # Place the order with risk checks
            result = await place_orders_with_risk_check(
                self.orders_client,
                self.accounts_client,
                self.quotes_client,
                self.selected_account,
                instrument_data,
                parsed_signal,
                position_sizes,
                risk_amount,
                max_drawdown_balance,
                colored_time
            )

            # Register orders with the missed signal handler
            if self.missed_signal_handler and signal_id and result and instrument_data:
                order_ids = []
                for order_info, response in result.get('successful', []):
                    if isinstance(response, dict) and 'd' in response and 'orderId' in response['d']:
                        order_ids.append(response['d']['orderId'])
                    elif isinstance(response, dict) and 'orderId' in response:
                        order_ids.append(response['orderId'])

                if order_ids:
                    self.missed_signal_handler.register_orders_for_signal(
                        parsed_signal['instrument'],
                        signal_id,
                        order_ids
                    )

        except KeyError as e:
            self.logger.error(
                f"{colored_time}: {Fore.RED}Error processing signal: Missing key {e}. Skipping this signal.{Style.RESET_ALL}")
        except Exception as e:
            self.logger.error(
                f"{colored_time}: {Fore.RED}Unexpected error: {e}. Skipping this signal.{Style.RESET_ALL}",
                exc_info=True)

    # -------------------------------------------------------------------------
    # Main Execution Methods
    # -------------------------------------------------------------------------

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
            await self.start_drawdown_monitor()

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


async def shutdown(loop):
    """Handle graceful shutdown when CTRL+C is pressed"""
    logging.info("Shutdown signal received. Closing all connections...")

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()
    logging.info("Shutdown complete.")


async def handle_risk_configuration():
    """Handle risk management configuration menu"""
    while True:
        risk_choice = display_risk_menu()

        if risk_choice == '1':
            # View current risk settings
            risk_config.display_current_risk_settings()
            input("\nPress Enter to continue...")

        elif risk_choice == '2':
            # Apply conservative profile
            confirmation = input(f"Apply {Fore.BLUE}Conservative{Style.RESET_ALL} risk profile? (y/n): ").lower()
            if confirmation == 'y':
                risk_config.apply_risk_profile("conservative")
                print(f"{Fore.GREEN}Conservative risk profile applied.{Style.RESET_ALL}")
                # Display the new settings
                risk_config.display_current_risk_settings()
                input("\nPress Enter to continue...")

        elif risk_choice == '3':
            # Apply balanced profile
            confirmation = input(f"Apply {Fore.GREEN}Balanced{Style.RESET_ALL} risk profile? (y/n): ").lower()
            if confirmation == 'y':
                risk_config.apply_risk_profile("balanced")
                print(f"{Fore.GREEN}Balanced risk profile applied.{Style.RESET_ALL}")
                # Display the new settings
                risk_config.display_current_risk_settings()
                input("\nPress Enter to continue...")

        elif risk_choice == '4':
            # Apply aggressive profile
            confirmation = input(
                f"Apply {Fore.RED}Aggressive{Style.RESET_ALL} risk profile? This uses higher risk percentages. Are you sure? (y/n): ").lower()
            if confirmation == 'y':
                risk_config.apply_risk_profile("aggressive")
                print(f"{Fore.GREEN}Aggressive risk profile applied.{Style.RESET_ALL}")
                # Display the new settings
                risk_config.display_current_risk_settings()
                input("\nPress Enter to continue...")

        # NEW OPTIONS FOR MANAGEMENT SETTINGS
        elif risk_choice == '5':
            # Toggle Auto-Breakeven
            new_value = risk_config.toggle_management_setting("auto_breakeven")
            status = "ENABLED" if new_value else "DISABLED"
            color = Fore.GREEN if new_value else Fore.RED
            print(f"{color}Auto-Breakeven is now {status}{Style.RESET_ALL}")

            # Note about profile impact
            print(f"{Fore.YELLOW}Note: This creates a custom profile based on your current settings.{Style.RESET_ALL}")
            input("\nPress Enter to continue...")

        elif risk_choice == '6':
            # Toggle Auto-Close Early
            new_value = risk_config.toggle_management_setting("auto_close_early")
            status = "ENABLED" if new_value else "DISABLED"
            color = Fore.GREEN if new_value else Fore.RED
            print(f"{color}Auto-Close Early is now {status}{Style.RESET_ALL}")

            # Note about profile impact
            print(f"{Fore.YELLOW}Note: This creates a custom profile based on your current settings.{Style.RESET_ALL}")
            input("\nPress Enter to continue...")

        elif risk_choice == '7':
            # Toggle Confirmation Required
            new_value = risk_config.toggle_management_setting("confirmation_required")
            status = "ENABLED" if new_value else "DISABLED"
            color = Fore.GREEN if new_value else Fore.RED
            print(f"{color}Confirmation Requirement is now {status}{Style.RESET_ALL}")

            # Warning if both auto features enabled and confirmation disabled
            mgmt_settings = risk_config.get_management_settings()
            if mgmt_settings.get("auto_breakeven", False) and mgmt_settings.get("auto_close_early",
                                                                                False) and not new_value:
                print(
                    f"{Fore.RED}Warning: Both auto features are enabled with no confirmation requirement.{Style.RESET_ALL}")
                print(
                    f"{Fore.RED}The bot will execute all signal provider instructions automatically.{Style.RESET_ALL}")

            # Note about profile impact
            print(f"{Fore.YELLOW}Note: This creates a custom profile based on your current settings.{Style.RESET_ALL}")
            input("\nPress Enter to continue...")

        elif risk_choice == '8':
            # Configure Forex risk
            print(f"\n{Fore.CYAN}Configuring Forex Risk Percentages{Style.RESET_ALL}")

            # Normal risk
            normal_risk = get_risk_percentage_input("Forex", is_reduced=False)
            if normal_risk:
                risk_config.update_risk_percentage("FOREX", normal_risk, is_reduced=False)

            # Reduced risk
            reduced_risk = get_risk_percentage_input("Forex", is_reduced=True)
            if reduced_risk:
                risk_config.update_risk_percentage("FOREX", reduced_risk, is_reduced=True)

            print(f"{Fore.GREEN}Forex risk settings updated.{Style.RESET_ALL}")

        elif risk_choice == '9':
            # Configure CFD risk
            print(f"\n{Fore.CYAN}Configuring CFD Risk Percentages{Style.RESET_ALL}")

            # Normal risk
            normal_risk = get_risk_percentage_input("CFD", is_reduced=False)
            if normal_risk:
                risk_config.update_risk_percentage("CFD", normal_risk, is_reduced=False)

            # Reduced risk
            reduced_risk = get_risk_percentage_input("CFD", is_reduced=True)
            if reduced_risk:
                risk_config.update_risk_percentage("CFD", reduced_risk, is_reduced=True)

            print(f"{Fore.GREEN}CFD risk settings updated.{Style.RESET_ALL}")

        elif risk_choice == '10':
            # Configure XAUUSD risk
            print(f"\n{Fore.CYAN}Configuring XAUUSD (Gold) Risk Percentages{Style.RESET_ALL}")

            # Normal risk
            normal_risk = get_risk_percentage_input("XAUUSD", is_reduced=False)
            if normal_risk:
                risk_config.update_risk_percentage("XAUUSD", normal_risk, is_reduced=False)

            # Reduced risk
            reduced_risk = get_risk_percentage_input("XAUUSD", is_reduced=True)
            if reduced_risk:
                risk_config.update_risk_percentage("XAUUSD", reduced_risk, is_reduced=True)

            print(f"{Fore.GREEN}XAUUSD risk settings updated.{Style.RESET_ALL}")

        elif risk_choice == '11':
            # Reset to defaults
            confirmation = input(
                f"{Fore.YELLOW}Are you sure you want to reset to default (balanced) risk settings? (y/n): {Style.RESET_ALL}").lower()
            if confirmation == 'y':
                risk_config.apply_risk_profile("balanced")
                print(f"{Fore.GREEN}Risk settings reset to defaults (balanced profile).{Style.RESET_ALL}")

        elif risk_choice == '12':
            # Return to main menu
            return

        else:
            print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

async def main():
    """Main entry point with Windows-compatible signal handling"""
    # Display banner first
    display_banner()

    while True:
        # Show menu and get choice
        choice = display_menu()

        if choice == '3':
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
            return  # Exit after bot finishes

        elif choice == '2':
            await handle_risk_configuration()

        else:
            print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")


if __name__ == "__main__":
    try:
        # On Windows, we rely on KeyboardInterrupt exception instead of signals
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
    except Exception as e:
        logging.error(f"Critical error: {e}", exc_info=True)
        sys.exit(1)