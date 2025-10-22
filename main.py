from core.signal_parser import find_matching_instrument
import config.risk_config as risk_config
from services.news_filter import NewsEventFilter
from services.pos_monitor import monitor_existing_position
from cli.display_menu import (
    display_menu,
    display_risk_menu,
    display_account_risk_menu,
    get_risk_percentage_input,
    get_drawdown_percentage_input
)
from services import multi_account_drawdown_manager
from services.drawdown_manager import (
    load_drawdown_data,
    schedule_daily_reset_async,
    max_drawdown_balance
)
from tradelocker_api.endpoints.quotes import TradeLockerQuotes
from tradelocker_api.endpoints.orders import TradeLockerOrders
from tradelocker_api.endpoints.instruments import TradeLockerInstruments
from tradelocker_api.endpoints.accounts import TradeLockerAccounts
from tradelocker_api.endpoints.auth import TradeLockerAuth
from core.risk_management import calculate_position_size
from core.signal_parser import parse_signal_async
from cli.banner import display_banner
from telethon import TelegramClient, events
from dotenv import load_dotenv
from colorama import init, Fore, Style
import sys
import signal
import platform
import pytz
import logging
import asyncio
import os
os.system('chcp 65001 >nul')


# Filter to suppress unwanted library messages
class StdoutFilter:
    def __init__(self, stream):
        self.stream = stream
        self.buffer = ""

    def write(self, text):
        # Suppress specific unwanted messages
        if "Got difference for account updates" in text:
            return
        self.stream.write(text)

    def flush(self):
        self.stream.flush()


# Apply stdout filter
sys.stdout = StdoutFilter(sys.stdout)

# Multi-account drawdown management


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

        # Multi-account tracking
        self.monitored_accounts = []  # List of accounts to monitor for daily drawdown

        # Tasks tracking
        self._tasks = set()
        self._shutdown_flag = False

    # -------------------------------------------------------------------------
    # Initialization and Setup Methods
    # -------------------------------------------------------------------------

    def _setup_logging(self):
        """Configure logging for the application"""
        from config.logging_config import setup_logging
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
        # self.channel_ids = [-1002153475473, -1002486712356]
        self.channel_ids = [-1002153475473, -1002486712356, -1002379218267, 2486712356]
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

            # Suppress Telethon library debug messages
            logging.getLogger('telethon').setLevel(logging.WARNING)

            # Connect first
            await self.client.connect()

            # Show current monitor channels
            await self.display_monitored_channels()
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
                pass  # Silent - already authenticated

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

            # Initialize news filter (silent)
            if self.enable_news_filter:
                await self.news_filter.initialize()
                # Schedule regular updates
                self._schedule_news_calendar_updates()

            # Initialize new Signal Manager
            from services.signal_management import SignalManager

            self.signal_manager = SignalManager(
                self.accounts_client,
                self.orders_client,
                self.instruments_client,
                self.auth
            )

            # Silent initialization - signal manager ready

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
            "Missed signal handler configured: "
            f"Fallback protection {'ENABLED' if enable_fallback else 'DISABLED'}, "
            f"Signal age limit: {max_signal_age_hours} hours, "
            f"Consider channel source: {'YES' if consider_channel else 'NO'}"
        )
        return True

    # --------------------------------------------------------------------------
    # Logging Methods
    # --------------------------------------------------------------------------

    def export_message_logs(self):
        """Export signal management message logs for debugging"""
        if hasattr(self, 'signal_manager') and hasattr(self.signal_manager, 'export_message_logs'):
            return self.signal_manager.export_message_logs()
        return "Message logging not available"

    async def analyze_recent_signals(self):
        """Analyze recent signals for debugging issues"""
        if not hasattr(self, 'signal_manager'):
            return "Signal manager not initialized"

        # Get logs
        logs = self.signal_manager.message_logs

        # Basic statistics
        management_count = sum(1 for log in logs if log.get('is_management', False))
        success_count = sum(1 for log in logs if log.get('is_management', False) and
                            log.get('success', False))

        # Group by match method
        match_methods = {}
        for log in logs:
            if log.get('is_management', False):
                method = log.get('match_method', 'unknown')
                match_methods[method] = match_methods.get(method, 0) + 1

        # Format results
        result = "Recent Signal Analysis:\n"
        result += f"Total messages: {len(logs)}\n"
        result += f"Management instructions: {management_count}\n"
        result += f"Successful executions: {success_count}\n\n"
        result += "Match methods used:\n"

        for method, count in match_methods.items():
            result += f"- {method}: {count}\n"

        return result

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
                self.orders_client,  # Add this parameter
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
        # Load drawdown data for the trading account (single account manager)
        load_drawdown_data(self.selected_account)

        # Validate and fix drawdown if needed for trading account
        from services.drawdown_manager import validate_and_fix_drawdown
        await validate_and_fix_drawdown(self.accounts_client, self.selected_account)

        # Schedule reset for trading account (single account)
        reset_task = asyncio.create_task(
            schedule_daily_reset_async(self.accounts_client, self.selected_account)
        )
        self._tasks.add(reset_task)
        reset_task.add_done_callback(self._tasks.discard)

        # Initialize multi-account drawdown tracking if we have monitored accounts
        if self.monitored_accounts and len(self.monitored_accounts) > 0:
            # Load existing multi-account data (silent)
            multi_account_drawdown_manager.load_accounts_drawdown()

            # Initialize drawdown for each monitored account (silent)
            for account in self.monitored_accounts:
                multi_account_drawdown_manager.initialize_account_drawdown(account)

            # Display current status
            multi_account_drawdown_manager.display_all_accounts_drawdown()

            # Schedule daily reset for all monitored accounts at 7 PM EST
            multi_reset_task = asyncio.create_task(
                multi_account_drawdown_manager.schedule_daily_reset_async(self.accounts_client)
            )
            self._tasks.add(multi_reset_task)
            multi_reset_task.add_done_callback(self._tasks.discard)

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
            from colorama import init, Fore, Style
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

    async def setup_multi_account_tracking(self, accounts_data):
        """Automatically set up drawdown tracking for ALL active accounts"""
        try:
            # Get only ACTIVE accounts
            active_accounts = [acc for acc in accounts_data['accounts'] if acc.get('status') == 'ACTIVE']

            if not active_accounts:
                self.logger.warning("⚠️  No active accounts available for tracking.")
                return False

            # Set all active accounts for monitoring
            self.monitored_accounts = active_accounts

            # Only show if multiple accounts
            if len(active_accounts) > 1:
                self.logger.info("")
                self.logger.info(f"🔔 Tracking {len(active_accounts)} accounts for daily drawdown reset")
                self.logger.info("")

            return True

        except Exception as e:
            self.logger.error(f"❌ Error setting up multi-account tracking: {e}")
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

            # Log message details for debugging
            self.logger.debug(f"Received message ID: {message_id}, Reply to: {reply_to_msg_id}, Channel: {channel_id}")

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
                    reply_to_msg_id=reply_to_msg_id,
                    message_id=message_id
                )
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def display_monitored_channels(self):
        """
        Display all Telegram channels being monitored by the bot.
        Shows only channel names and status - clean and simple.
        """
        try:
            if not self.channel_ids or len(self.channel_ids) == 0:
                self.logger.warning("⚠️  No channels configured for monitoring!")
                return

            self.logger.info("")
            self.logger.info("📡 ══════════════════════════════════════════════════")
            self.logger.info(f"   MONITORING {len(self.channel_ids)} TELEGRAM CHANNEL(S)")
            self.logger.info("   ══════════════════════════════════════════════════")

            # Track statistics
            accessible_count = 0
            inaccessible_count = 0

            # Check each channel
            for channel_id in self.channel_ids:
                try:
                    # Try to get entity information
                    entity = await self.client.get_entity(channel_id)

                    # Extract channel information
                    channel_name = entity.title if hasattr(entity, 'title') else 'Unknown'

                    # Success - channel is accessible
                    accessible_count += 1
                    self.logger.info(f"   ✅ {channel_name}")

                except Exception as e:
                    # Channel not accessible
                    inaccessible_count += 1
                    self.logger.info(f"   ❌ Channel ID {channel_id} - Not accessible")

            self.logger.info("   ══════════════════════════════════════════════════")

            if inaccessible_count > 0:
                self.logger.warning(f"   ⚠️  {inaccessible_count} channel(s) not accessible")

            self.logger.info("")

        except Exception as e:
            self.logger.error(f"❌ Error checking channels: {e}")
    # -------------------------------------------------------------------------
    # Trading Signal Processing Methods
    # -------------------------------------------------------------------------

    async def process_message(self, message_text, colored_time, event=None, channel_id=None,
                              channel_name=None, reply_to_msg_id=None, message_id=None):
        """
        Process a received Telegram message - updated to ensure message_id is passed for caching
        """
        try:
            # Log the message ID for debugging
            self.logger.debug(f"Processing message with ID {message_id}, replying to {reply_to_msg_id}")

            # First, check if this is a command message via SignalManager
            if self.signal_manager:
                is_handled, result = await self.signal_manager.handle_message(
                    message_text,
                    self.selected_account,
                    colored_time,
                    reply_to_msg_id,
                    message_id
                )

                if is_handled:
                    # Log result information
                    command_type = result.get("command_type", "unknown")
                    success_count = result.get("success_count", 0)
                    total_count = result.get("total_count", 0)

                    if success_count > 0:
                        self.logger.info(
                            f"{colored_time}: {Fore.GREEN}Successfully executed {command_type} "
                            f"command on {success_count}/{total_count} orders{Style.RESET_ALL}"
                        )
                    else:
                        self.logger.warning(
                            f"{colored_time}: {Fore.YELLOW}Failed to execute {command_type} command. "
                            f"No orders were successfully processed.{Style.RESET_ALL}"
                        )
                    return

            # If not a command, parse as a trading signal
            parsed_signal = await parse_signal_async(message_text)
            if parsed_signal is None:
                # Silent - message was not a valid trading signal
                return

            # Check if this is a reduced risk signal
            reduced_risk = parsed_signal.get('reduced_risk', False)
            risk_emoji = "⚠️ REDUCED RISK" if reduced_risk else ""

            # Clean signal notification with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            direction = parsed_signal['order_type'].upper()
            instrument = parsed_signal['instrument']
            entry = parsed_signal['entry_point']
            sl = parsed_signal['stop_loss']
            tps = ', '.join(map(str, parsed_signal['take_profits']))

            self.logger.info("")
            self.logger.info(f"📊 [{timestamp}] NEW SIGNAL {risk_emoji}")
            self.logger.info(f"   {instrument} {direction} @ {entry}")
            self.logger.info(f"   🛡️  SL: {sl} | 🎯 TP: {tps}")
            self.logger.info("")

            # Apply TP filtering based on user preferences
            from core.signal_parser import filter_take_profits_by_preference
            tp_selection = risk_config.get_tp_selection()
            filtered_tps = filter_take_profits_by_preference(parsed_signal['take_profits'], tp_selection)

            # Update the parsed signal with filtered TPs
            original_tps = parsed_signal['take_profits'].copy()
            parsed_signal['take_profits'] = filtered_tps

            # Log the TP selection if it's different from original
            if len(filtered_tps) < len(original_tps):
                # Show TP selection briefly
                self.logger.info(f"   📌 Using {len(filtered_tps)} of {len(original_tps)} TPs ({tp_selection['mode']})")

            # Check news restrictions if enabled
            if self.enable_news_filter:
                current_time = datetime.now(pytz.UTC)
                try:
                    can_trade, reason = self.news_filter.can_place_order(parsed_signal, current_time)

                    if not can_trade:
                        self.logger.warning(f"   🚫 Trade blocked: {reason}")
                        return
                except AttributeError as e:
                    self.logger.error(f"   ❌ Error: {e}")
                    return

            # Refresh account data to get latest balance
            self.selected_account = await self.accounts_client.refresh_account_balance_async() or self.selected_account
            float(self.selected_account['accountBalance'])

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

            # Debug only - position sizes calculated
            self.logger.debug(f"Position sizes: {position_sizes}")

            # Display risk information
            risk_percentage = "0.5%" if reduced_risk else "1.0%"  # Approximate values for display
            risk_profile = risk_config.detect_current_profile()
            self.logger.info(f"{colored_time}: {Fore.CYAN}Using {risk_profile} risk profile: {risk_percentage} " +
                             f"({Fore.RED}REDUCED{Style.RESET_ALL} due to signal keywords)" if reduced_risk else "")

            # Place the order with risk checks - IMPORTANT: Pass the message_id for caching
            from services.order_handler import place_orders_with_risk_check

            # Ensure we're passing message_id - this is the key change
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
                colored_time,
                message_id=message_id  # Pass message_id for caching
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

            # Automatically set up multi-account tracking for ALL active accounts
            if not await self.setup_multi_account_tracking(accounts_data):
                self.logger.warning("Failed to set up multi-account tracking. Continuing with trading account only.")
                self.monitored_accounts = [self.selected_account]

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


async def handle_tp_selection(account_id=None):
    """
    Handle take profit selection configuration

    Args:
        account_id: Account number (None for global defaults)
    """
    while True:
        from cli.display_menu import display_tp_selection_menu
        import config.risk_config as risk_config
        from colorama import Fore, Style

        tp_choice = display_tp_selection_menu()

        if tp_choice == '1':
            risk_config.update_tp_selection("all", account_id=account_id)
            print(f"{Fore.GREEN}Now using all take profits from signals.{Style.RESET_ALL}")

        elif tp_choice == '2':
            risk_config.update_tp_selection("first_only", account_id=account_id)
            print(f"{Fore.GREEN}Now using only the first take profit (TP1).{Style.RESET_ALL}")

        elif tp_choice == '3':
            risk_config.update_tp_selection("first_two", account_id=account_id)
            print(f"{Fore.GREEN}Now using only the first two take profits.{Style.RESET_ALL}")

        elif tp_choice == '4':
            risk_config.update_tp_selection("last_two", account_id=account_id)
            print(f"{Fore.GREEN}Now using only the last two take profits.{Style.RESET_ALL}")

        elif tp_choice == '5':
            risk_config.update_tp_selection("odd", account_id=account_id)
            print(f"{Fore.GREEN}Now using odd-numbered take profits (TP1, TP3, etc.).{Style.RESET_ALL}")

        elif tp_choice == '6':
            risk_config.update_tp_selection("even", account_id=account_id)
            print(f"{Fore.GREEN}Now using even-numbered take profits (TP2, TP4, etc.).{Style.RESET_ALL}")

        elif tp_choice == '7':
            # Custom selection interface
            custom_input = input(
                f"{Fore.YELLOW}Enter TP numbers to use, separated by commas (e.g., 1,3,4): {Style.RESET_ALL}")
            try:
                # Parse the input into a list of integers
                custom_selection = [int(x.strip()) for x in custom_input.split(',')]
                if not custom_selection:
                    print(f"{Fore.RED}Invalid selection. Must include at least one TP.{Style.RESET_ALL}")
                    continue

                risk_config.update_tp_selection("custom", custom_selection, account_id=account_id)
                tp_list = ', '.join([f'TP{i}' for i in custom_selection])
                print(f"{Fore.GREEN}Now using custom selection: {tp_list}{Style.RESET_ALL}")

            except ValueError:
                print(f"{Fore.RED}Invalid input. Please enter numbers separated by commas.{Style.RESET_ALL}")

        elif tp_choice == '8':
            return

        else:
            print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

        input("\nPress Enter to continue...")


async def handle_account_specific_configuration(account_id):
    """
    Handle risk configuration for a specific account

    Args:
        account_id: The account number to configure
    """
    while True:
        risk_choice = display_account_risk_menu(account_id)

        if risk_choice == '1':
            # View current risk settings
            risk_config.display_current_risk_settings(account_id)
            input("\nPress Enter to continue...")

        elif risk_choice == '2':
            # Apply conservative profile
            confirmation = input(f"Apply {Fore.BLUE}Conservative{Style.RESET_ALL} risk profile? (y/n): ").lower()
            if confirmation == 'y':
                risk_config.apply_risk_profile("conservative", account_id)
                print(f"{Fore.GREEN}Conservative risk profile applied.{Style.RESET_ALL}")
                risk_config.display_current_risk_settings(account_id)
                input("\nPress Enter to continue...")

        elif risk_choice == '3':
            # Apply balanced profile
            confirmation = input(f"Apply {Fore.GREEN}Balanced{Style.RESET_ALL} risk profile? (y/n): ").lower()
            if confirmation == 'y':
                risk_config.apply_risk_profile("balanced", account_id)
                print(f"{Fore.GREEN}Balanced risk profile applied.{Style.RESET_ALL}")
                risk_config.display_current_risk_settings(account_id)
                input("\nPress Enter to continue...")

        elif risk_choice == '4':
            # Apply aggressive profile
            confirmation = input(f"Apply {Fore.RED}Aggressive{Style.RESET_ALL} risk profile? (y/n): ").lower()
            if confirmation == 'y':
                risk_config.apply_risk_profile("aggressive", account_id)
                print(f"{Fore.GREEN}Aggressive risk profile applied.{Style.RESET_ALL}")
                risk_config.display_current_risk_settings(account_id)
                input("\nPress Enter to continue...")

        elif risk_choice == '5':
            # Configure Forex risk
            print(f"\n{Fore.CYAN}Configuring Forex Risk Percentages{Style.RESET_ALL}")

            # Normal risk
            normal_risk = get_risk_percentage_input("Forex", is_reduced=False)
            if normal_risk:
                risk_config.update_risk_percentage("FOREX", normal_risk, is_reduced=False, account_id=account_id)

            # Reduced risk
            reduced_risk = get_risk_percentage_input("Forex", is_reduced=True)
            if reduced_risk:
                risk_config.update_risk_percentage("FOREX", reduced_risk, is_reduced=True, account_id=account_id)

            print(f"{Fore.GREEN}Forex risk settings updated.{Style.RESET_ALL}")
            input("\nPress Enter to continue...")

        elif risk_choice == '6':
            # Configure CFD risk
            print(f"\n{Fore.CYAN}Configuring CFD Risk Percentages{Style.RESET_ALL}")

            # Normal risk
            normal_risk = get_risk_percentage_input("CFD", is_reduced=False)
            if normal_risk:
                risk_config.update_risk_percentage("CFD", normal_risk, is_reduced=False, account_id=account_id)

            # Reduced risk
            reduced_risk = get_risk_percentage_input("CFD", is_reduced=True)
            if reduced_risk:
                risk_config.update_risk_percentage("CFD", reduced_risk, is_reduced=True, account_id=account_id)

            print(f"{Fore.GREEN}CFD risk settings updated.{Style.RESET_ALL}")
            input("\nPress Enter to continue...")

        elif risk_choice == '7':
            # Configure XAUUSD risk
            print(f"\n{Fore.CYAN}Configuring XAUUSD (Gold) Risk Percentages{Style.RESET_ALL}")

            # Normal risk
            normal_risk = get_risk_percentage_input("XAUUSD", is_reduced=False)
            if normal_risk:
                risk_config.update_risk_percentage("XAUUSD", normal_risk, is_reduced=False, account_id=account_id)

            # Reduced risk
            reduced_risk = get_risk_percentage_input("XAUUSD", is_reduced=True)
            if reduced_risk:
                risk_config.update_risk_percentage("XAUUSD", reduced_risk, is_reduced=True, account_id=account_id)

            print(f"{Fore.GREEN}XAUUSD risk settings updated.{Style.RESET_ALL}")
            input("\nPress Enter to continue...")

        elif risk_choice == '8':
            # Configure Daily Drawdown percentage
            print(f"\n{Fore.CYAN}Configuring Daily Drawdown Percentage{Style.RESET_ALL}")

            # Get new drawdown percentage
            new_drawdown = get_drawdown_percentage_input()
            if new_drawdown:
                risk_config.update_drawdown_percentage(new_drawdown, account_id)
                print(f"{Fore.GREEN}Daily drawdown percentage updated to {new_drawdown:.1f}%.{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}Note: This creates a custom profile based on your current settings.{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}The new setting will apply after the next daily reset.{Style.RESET_ALL}")

            input("\nPress Enter to continue...")

        elif risk_choice == '9':
            # Reset to defaults
            confirmation = input(
                f"{Fore.YELLOW}Are you sure you want to reset to default (balanced) risk settings? (y/n): {Style.RESET_ALL}").lower()  # noqa: E501
            if confirmation == 'y':
                risk_config.apply_risk_profile("balanced", account_id)
                print(f"{Fore.GREEN}Risk settings reset to defaults (balanced profile).{Style.RESET_ALL}")
                input("\nPress Enter to continue...")

        elif risk_choice == '10':
            # Configure Take Profit Selection
            await handle_tp_selection(account_id)

        elif risk_choice == '12' and account_id is not None:
            # Delete custom settings for this account
            confirmation = input(
                f"{Fore.YELLOW}Delete custom settings for account {account_id}? This will revert to global defaults. (y/n): {Style.RESET_ALL}").lower()  # noqa: E501
            if confirmation == 'y':
                risk_config.delete_account_settings(account_id)
                print(f"{Fore.GREEN}Custom settings deleted. Account {account_id} now uses global defaults.{Style.RESET_ALL}")
                input("\nPress Enter to continue...")
                return  # Return to previous menu

        elif risk_choice == '11':
            # Return to previous menu
            return

        else:
            print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")


async def handle_risk_configuration():
    """Handle risk management configuration menu"""
    while True:
        risk_choice = display_risk_menu()

        if risk_choice == '1':
            # Configure global default settings
            await handle_account_specific_configuration(None)

        elif risk_choice == '2':
            # Configure per-account settings
            account_id = input(f"\n{Fore.GREEN}Enter account number to configure: {Style.RESET_ALL}").strip()
            if account_id:
                await handle_account_specific_configuration(account_id)
            else:
                print(f"{Fore.RED}Invalid account number{Style.RESET_ALL}")
                input("\nPress Enter to continue...")

        elif risk_choice == '3':
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
        logging.error("Critical error: {e}", exc_info=True)
        sys.exit(1)
