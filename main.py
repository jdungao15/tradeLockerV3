#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trading Bot Main Module
Ensures UTF-8 encoding across all platforms (Windows, Linux, macOS)
"""
import sys
import os

# Force UTF-8 encoding for the entire application (must be done before other imports)
if sys.version_info >= (3, 7):
    # Python 3.7+ supports reconfigure
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Set environment variables for UTF-8 (important for Linux)
os.environ['PYTHONIOENCODING'] = 'utf-8'
if 'LANG' not in os.environ:
    os.environ['LANG'] = 'en_US.UTF-8'
if 'LC_ALL' not in os.environ:
    os.environ['LC_ALL'] = 'en_US.UTF-8'

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

        # Initialize account-channel manager BEFORE loading config
        # (config loading needs to access it)
        from config.account_channels import AccountChannelManager
        self.account_channel_manager = AccountChannelManager()

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
        self.multi_account_mode = False  # Flag for multi-account trading mode

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

        # Load monitored channels from AccountChannelManager
        # This includes all channels from configured accounts + global channels
        self.channel_ids = self.account_channel_manager.get_all_monitored_channels()

        # Fallback to hardcoded channels if no channels configured
        if not self.channel_ids:
            self.logger.warning("No channels configured in account_channels.json, using hardcoded fallback")
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
        needs_reset = load_drawdown_data(self.selected_account)

        # If drawdown is from a previous day, reset it now
        if needs_reset:
            from services.drawdown_manager import reset_daily_drawdown_async
            self.logger.info("🔄 Resetting drawdown to current account balance...")
            await reset_daily_drawdown_async(self.accounts_client, self.selected_account)

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

            # Check each account and reset if from previous day
            for account in self.monitored_accounts:
                needs_reset = multi_account_drawdown_manager.check_and_reset_if_needed(account)
                multi_account_drawdown_manager.initialize_account_drawdown(account, force_reset=needs_reset)

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

            # Filter for only ACTIVE accounts and sort by Account Number (descending)
            all_accounts = accounts_data.get('accounts', [])
            accounts = sorted(
                [acc for acc in all_accounts if acc.get('status') == 'ACTIVE'],
                key=lambda x: int(x['accNum']),
                reverse=True
            )

            if not accounts:
                self.logger.info("No active accounts available.")
                return None

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

            # Print bottom border
            print(f"{Fore.CYAN}{Style.BRIGHT}{'═' * total_width}{Style.RESET_ALL}")

            # Add timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"{Fore.CYAN}{'Account data as of ' + timestamp:^{total_width}}{Style.RESET_ALL}\n")

            # Return the full accounts_data structure, but replace accounts list with active only
            accounts_data['accounts'] = accounts
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
        """Set up the Telegram message handler with multi-account routing"""
        if not self.enable_signals:
            self.logger.info("Signal processing is disabled. Skipping Telegram handler setup.")
            return

        @self.client.on(events.NewMessage(chats=self.channel_ids))
        async def handler(event):
            if self._shutdown_flag:
                return

            # Get message text and ensure proper UTF-8 encoding
            message_text = event.message.message

            # Normalize text encoding to handle any platform-specific issues
            if isinstance(message_text, bytes):
                message_text = message_text.decode('utf-8', errors='replace')
            elif isinstance(message_text, str):
                # Ensure the string is properly encoded/decoded
                try:
                    message_text = message_text.encode('utf-8').decode('utf-8')
                except (UnicodeDecodeError, UnicodeEncodeError):
                    # If encoding fails, use replace to handle problematic characters
                    message_text = message_text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')

            message_time_utc = event.message.date

            # Extract channel information
            chat = event.chat if hasattr(event, 'chat') else None
            channel_id = int(chat.id) if chat else None
            channel_name = chat.title if chat and hasattr(chat, 'title') else None

            # Extract message and reply information
            message_id = str(event.message.id) if hasattr(event.message, 'id') else None
            reply_to_msg_id = None

            # Check if this is a reply to another message
            if hasattr(event.message, 'reply_to') and event.message.reply_to:
                reply_to_msg_id = str(event.message.reply_to.reply_to_msg_id)
                self.logger.debug(f"Message is a reply to message ID: {reply_to_msg_id}")

            # Log message details for debugging
            self.logger.debug(f"Received message from channel {channel_id} ({channel_name}): {message_text[:50]}...")

            # Convert the UTC time to local time zone
            message_time_local = message_time_utc.astimezone(self.local_timezone)
            formatted_time = message_time_local.strftime('%Y-%m-%d %H:%M:%S')
            colored_time = f"{Fore.CYAN}[{formatted_time}]{Style.RESET_ALL}"

            # Check trading mode and route accordingly
            if self.multi_account_mode:
                # Multi-account mode: Route signals to configured accounts
                trading_accounts = self.account_channel_manager.get_accounts_for_channel(channel_id)

                if trading_accounts:
                    # Log which accounts will process this signal
                    account_names = [f"{acc['name']} (#{acc['accNum']})" for acc in trading_accounts]
                    self.logger.info(
                        f"{colored_time}: {Fore.CYAN}📨 Signal from {channel_name or 'Channel ' + str(channel_id)}{Style.RESET_ALL}"
                    )
                    self.logger.info(
                        f"   {Fore.GREEN}→ Processing for: {', '.join(account_names)}{Style.RESET_ALL}"
                    )

                    tasks = []
                    for account_config in trading_accounts:
                        task = asyncio.create_task(
                            self.process_message_for_account(
                                message_text,
                                colored_time,
                                event,
                                account_config,
                                channel_id=channel_id,
                                channel_name=channel_name,
                                reply_to_msg_id=reply_to_msg_id,
                                message_id=message_id
                            )
                        )
                        tasks.append(task)
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)

                    # Wait for all account tasks to complete
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    # No accounts configured for this channel in multi-account mode
                    self.logger.info(
                        f"{colored_time}: {Fore.YELLOW}⚠️  Signal from {channel_name or 'Channel ' + str(channel_id)} - No accounts configured for this channel{Style.RESET_ALL}"
                    )
            else:
                # Single-account mode: Use the selected account
                self.logger.debug(
                    f"Single-account mode: Processing signal with selected account"
                )

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
        Shows channel names, status, and configured accounts for multi-account mode.
        """
        try:
            if not self.channel_ids or len(self.channel_ids) == 0:
                self.logger.warning("⚠️  No channels configured for monitoring!")
                return

            self.logger.info("")
            self.logger.info("📡 ══════════════════════════════════════════════════")
            self.logger.info(f"   MONITORING {len(self.channel_ids)} TELEGRAM CHANNEL(S)")

            # Show trading mode
            if self.multi_account_mode:
                self.logger.info(f"   {Fore.GREEN}Mode: Multi-Account Trading{Style.RESET_ALL}")
            else:
                self.logger.info(f"   {Fore.YELLOW}Mode: Single-Account Trading{Style.RESET_ALL}")

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

                    if self.multi_account_mode:
                        # In multi-account mode, show which accounts are configured for this channel
                        trading_accounts = self.account_channel_manager.get_accounts_for_channel(channel_id)

                        if trading_accounts:
                            # Show which accounts will trade from this channel with account numbers
                            account_display = [f"{acc['name']} (#{acc['accNum']})" for acc in trading_accounts]
                            self.logger.info(f"   ✅ {channel_name}")
                            self.logger.info(f"      💼 Trading: {', '.join(account_display)}")
                        else:
                            # No accounts configured for this channel
                            self.logger.info(f"   ✅ {channel_name} (no accounts configured)")
                    else:
                        # In single-account mode, just show the channel name
                        self.logger.info(f"   ✅ {channel_name}")

                except Exception as e:
                    # Channel not accessible
                    inaccessible_count += 1
                    self.logger.info(f"   ❌ Channel ID {channel_id} - Not accessible")

            self.logger.info("   ══════════════════════════════════════════════════")

            if inaccessible_count > 0:
                self.logger.warning(f"   ⚠️  {inaccessible_count} channel(s) not accessible")

            # Show account-channel configuration summary (only in multi-account mode)
            if self.multi_account_mode:
                enabled_accounts = self.account_channel_manager.get_enabled_accounts()
                if enabled_accounts:
                    self.logger.info("")
                    self.logger.info(f"   📋 Multi-Account Configuration: {len(enabled_accounts)} account(s)")
                    for account_key, config in enabled_accounts.items():
                        channels = config.get('monitored_channels', [])
                        self.logger.info(f"      • {config['name']} (#{config['accNum']}): {len(channels)} channel(s)")

            self.logger.info("")

        except Exception as e:
            self.logger.error(f"❌ Error checking channels: {e}")
    # -------------------------------------------------------------------------
    # Trading Signal Processing Methods
    # -------------------------------------------------------------------------

    async def process_message_for_account(self, message_text, colored_time, event, account_config,
                                          channel_id=None, channel_name=None, reply_to_msg_id=None,
                                          message_id=None):
        """
        Process a message for a specific account (multi-account mode)

        Args:
            message_text: The message content
            colored_time: Formatted timestamp
            event: Telegram event
            account_config: Account configuration from AccountChannelManager
            channel_id: Telegram channel ID
            channel_name: Channel name
            reply_to_msg_id: Reply message ID
            message_id: Message ID
        """
        try:
            # Get the account from TradeLocker
            account_id = account_config['account_id']
            account_num = account_config['accNum']
            account_name = account_config['name']

            # Get the full account object from the accounts client
            accounts_data = await self.accounts_client.get_accounts_async()
            trading_account = next(
                (acc for acc in accounts_data['accounts'] if acc['id'] == account_id),
                None
            )

            if not trading_account:
                self.logger.warning(f"Account {account_name} (ID: {account_id}) not found in TradeLocker")
                return

            # DO NOT set selected account in multi-account mode to avoid race conditions
            # Each account processes independently with its own context

            # Log which account is processing this signal
            self.logger.debug(f"Processing signal for account: {account_name} (#{account_num})")

            # First, check if this is a command message via SignalManager
            if self.signal_manager:
                is_handled, result = await self.signal_manager.handle_message(
                    message_text,
                    trading_account,
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
                            f"{colored_time}: {Fore.GREEN}[{account_name}] Successfully executed {command_type} "
                            f"command on {success_count}/{total_count} orders{Style.RESET_ALL}"
                        )
                    else:
                        self.logger.warning(
                            f"{colored_time}: {Fore.YELLOW}[{account_name}] Failed to execute {command_type} command. "
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

            # Clean signal notification with account name
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            direction = parsed_signal['order_type'].upper()
            instrument = parsed_signal['instrument']
            entry = parsed_signal['entry_point']
            sl = parsed_signal['stop_loss']
            tps = ', '.join(map(str, parsed_signal['take_profits']))

            self.logger.info("")
            self.logger.info(f"📊 [{timestamp}] NEW SIGNAL for {Fore.CYAN}{account_name}{Style.RESET_ALL} {risk_emoji}")
            self.logger.info(f"   {instrument} {direction} @ {entry}")
            self.logger.info(f"   🛡️  SL: {sl} | 🎯 TP: {tps}")
            self.logger.info("")

            # Apply TP filtering based on user preferences
            from core.signal_parser import filter_take_profits_by_preference
            tp_selection = risk_config.get_tp_selection(account_num)
            filtered_tps = filter_take_profits_by_preference(parsed_signal['take_profits'], tp_selection)

            # Update the parsed signal with filtered TPs
            original_tps = parsed_signal['take_profits'].copy()
            parsed_signal['take_profits'] = filtered_tps

            # Log the TP selection if it's different from original
            if len(filtered_tps) < len(original_tps):
                self.logger.info(f"   📌 Using {len(filtered_tps)} of {len(original_tps)} TPs ({tp_selection['mode']})")

            # Check news restrictions if enabled
            if self.enable_news_filter:
                current_time = datetime.now(pytz.UTC)
                try:
                    can_trade, reason = self.news_filter.can_place_order(parsed_signal, current_time)

                    if not can_trade:
                        self.logger.warning(f"   🚫 [{account_name}] Trade blocked: {reason}")
                        return
                except AttributeError as e:
                    self.logger.error(f"   ❌ [{account_name}] Error: {e}")
                    return

            # Refresh account data to get latest balance (use direct API call to avoid shared state)
            account_state = await self.accounts_client.get_account_state_async(trading_account['id'], trading_account['accNum'])
            if account_state and 'd' in account_state:
                # Update the account balance with fresh data
                trading_account['accountBalance'] = account_state['d'].get('balance', trading_account['accountBalance'])

            refreshed_account = trading_account
            float(refreshed_account['accountBalance'])

            # Get instrument details
            instrument_data = await find_matching_instrument(
                self.instruments_client,
                refreshed_account,
                parsed_signal
            )

            if not instrument_data:
                self.logger.warning(
                    f"{colored_time}: {Fore.RED}[{account_name}] Instrument {parsed_signal['instrument']} not found. Skipping this signal.{Style.RESET_ALL}"
                )
                return

            # Calculate position sizes based on risk management (account-specific)
            position_sizes, risk_amount = calculate_position_size(
                instrument_data,
                parsed_signal['entry_point'],
                parsed_signal['stop_loss'],
                parsed_signal['take_profits'],
                refreshed_account,
                reduced_risk
            )

            # Display risk information
            risk_percentage = risk_config.get_risk_percentage(
                instrument_data.get('tradableInstrumentType', 'FOREX'),
                reduced_risk,
                account_num
            ) * 100
            risk_profile = risk_config.detect_current_profile(account_num)
            self.logger.info(
                f"{colored_time}: {Fore.CYAN}[{account_name}] Using {risk_profile} risk profile: {risk_percentage:.1f}%{Style.RESET_ALL}"
            )

            # Place the order with risk checks
            from services.order_handler import place_orders_with_risk_check

            result = await place_orders_with_risk_check(
                self.orders_client,
                self.accounts_client,
                self.quotes_client,
                refreshed_account,
                instrument_data,
                parsed_signal,
                position_sizes,
                risk_amount,
                max_drawdown_balance,
                colored_time,
                message_id=message_id
            )

        except KeyError as e:
            self.logger.error(
                f"{colored_time}: {Fore.RED}[{account_name}] Error processing signal: Missing key {e}. Skipping this signal.{Style.RESET_ALL}"
            )
        except Exception as e:
            self.logger.error(
                f"{colored_time}: {Fore.RED}[{account_name}] Unexpected error: {e}. Skipping this signal.{Style.RESET_ALL}",
                exc_info=True
            )

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

            # Check if multi-account mode is configured
            enabled_accounts = self.account_channel_manager.get_enabled_accounts()

            if enabled_accounts:
                # Multi-account configuration exists, ask user which mode to use
                print(f"\n{Fore.CYAN}═══════════════════════════════════════════════════{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}Multi-Account Configuration Detected{Style.RESET_ALL}")
                print(f"{Fore.CYAN}═══════════════════════════════════════════════════{Style.RESET_ALL}")
                print(f"\n{len(enabled_accounts)} account(s) configured for multi-account trading:")
                for account_key, config in enabled_accounts.items():
                    channels = config.get('monitored_channels', [])
                    print(f"  • {config['name']} (#{config['accNum']}): {len(channels)} channel(s)")

                print(f"\n{Fore.CYAN}Select Trading Mode:{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}1.{Style.RESET_ALL} Multi-Account Mode (route signals to configured accounts)")
                print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Single-Account Mode (select one account)")

                mode_choice = input(f"\n{Fore.GREEN}Enter your choice (1-2): {Style.RESET_ALL}").strip()

                if mode_choice == '1':
                    # Multi-account mode
                    self.multi_account_mode = True
                    self.logger.info(f"\n{Fore.GREEN}✅ Multi-Account Mode Enabled{Style.RESET_ALL}")
                    self.logger.info(f"Signals will be routed to configured accounts based on channel")

                    # Show routing configuration
                    self.logger.info(f"\n{Fore.CYAN}📋 Channel Routing Configuration:{Style.RESET_ALL}")
                    all_channels = self.account_channel_manager.get_all_monitored_channels()
                    for ch_id in all_channels:
                        accounts_for_channel = self.account_channel_manager.get_accounts_for_channel(ch_id)
                        if accounts_for_channel:
                            account_names = [f"{acc['name']} (#{acc['accNum']})" for acc in accounts_for_channel]
                            self.logger.info(f"   Channel {ch_id}: {', '.join(account_names)}")
                        else:
                            self.logger.info(f"   Channel {ch_id}: {Fore.YELLOW}No accounts configured{Style.RESET_ALL}")
                    self.logger.info("")

                    # For multi-account mode, select the first enabled account for monitoring/drawdown
                    # (this is just for the monitoring system, actual trading uses configured accounts)
                    first_account_id = list(enabled_accounts.values())[0]['account_id']
                    self.selected_account = next(
                        (acc for acc in accounts_data['accounts'] if acc['id'] == first_account_id),
                        None
                    )

                    if not self.selected_account:
                        self.logger.error("Failed to initialize multi-account mode. Falling back to single-account.")
                        self.multi_account_mode = False
                        if not await self.select_account(accounts_data):
                            self.logger.error("Account selection failed. Exiting.")
                            return
                else:
                    # Single-account mode
                    self.multi_account_mode = False
                    self.logger.info(f"\n{Fore.YELLOW}Single-Account Mode Selected{Style.RESET_ALL}\n")
                    if not await self.select_account(accounts_data):
                        self.logger.error("Account selection failed. Exiting.")
                        return
            else:
                # No multi-account configuration, use single-account mode
                self.multi_account_mode = False
                self.logger.info(f"{Fore.YELLOW}No multi-account configuration found. Using single-account mode.{Style.RESET_ALL}\n")
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


async def get_tradelocker_accounts():
    """Get TradeLocker accounts without initializing Telegram client"""
    try:
        # Only initialize TradeLocker API clients
        auth = TradeLockerAuth()
        await auth.authenticate_async()

        if not await auth.get_access_token_async():
            print(f"{Fore.RED}Failed to authenticate with TradeLocker API{Style.RESET_ALL}")
            return None

        # Initialize accounts client
        accounts_client = TradeLockerAccounts(auth)
        accounts_data = await accounts_client.get_accounts_async()

        # Cleanup
        await auth.close()
        if hasattr(accounts_client, 'close'):
            await accounts_client.close()

        return accounts_data

    except Exception as e:
        print(f"{Fore.RED}Error connecting to TradeLocker: {e}{Style.RESET_ALL}")
        return None


async def get_channel_names(channel_ids):
    """
    Get channel names from Telegram for the given channel IDs

    Args:
        channel_ids: List of channel IDs

    Returns:
        dict: Mapping of channel_id -> channel_name
    """
    if not channel_ids:
        return {}

    channel_names = {}
    client = None

    try:
        # Load environment variables
        load_dotenv()
        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')

        # Initialize Telegram client
        client = TelegramClient('./my_session', int(api_id), api_hash)

        # Suppress Telethon library debug messages
        logging.getLogger('telethon').setLevel(logging.WARNING)

        # Connect
        await client.connect()

        # Check if authorized
        if not await client.is_user_authorized():
            # Can't fetch names without authorization
            return {}

        # Fetch channel names
        for channel_id in channel_ids:
            try:
                entity = await client.get_entity(channel_id)
                channel_name = entity.title if hasattr(entity, 'title') else f"Channel {channel_id}"
                channel_names[channel_id] = channel_name
            except Exception as e:
                # If we can't get the channel name, use the ID
                channel_names[channel_id] = f"Channel {channel_id}"

        return channel_names

    except Exception as e:
        # If any error occurs, return empty dict (will fall back to IDs)
        return {}

    finally:
        # Cleanup
        if client:
            await client.disconnect()


async def handle_account_channel_configuration():
    """Handle account-channel routing configuration menu"""
    from cli.account_channel_menu import (
        display_account_channel_menu,
        configure_account_channels,
        toggle_account_trading,
        add_channel_to_account,
        remove_channel_from_account,
        setup_new_account
    )
    from config.account_channels import AccountChannelManager

    # Create account manager instance (no bot needed)
    account_manager = AccountChannelManager()

    while True:
        choice = display_account_channel_menu()

        if choice == '1':
            # View current configuration
            # Fetch channel names from Telegram for better display
            all_channels = account_manager.get_all_monitored_channels()
            channel_names = await get_channel_names(all_channels)
            print(account_manager.get_summary(channel_names))
            input("\nPress Enter to continue...")

        elif choice == '2':
            # Configure account channels
            configure_account_channels(account_manager)

        elif choice == '3':
            # Enable/Disable account trading
            toggle_account_trading(account_manager)

        elif choice == '4':
            # Add channel to account
            add_channel_to_account(account_manager)

        elif choice == '5':
            # Remove channel from account
            remove_channel_from_account(account_manager)

        elif choice == '6':
            # Set up new account
            # Need to get accounts data from TradeLocker (without Telegram)
            try:
                print(f"{Fore.CYAN}Connecting to TradeLocker API...{Style.RESET_ALL}")
                accounts_data = await get_tradelocker_accounts()

                if accounts_data:
                    setup_new_account(account_manager, accounts_data)
                else:
                    print(f"{Fore.RED}Failed to retrieve accounts from TradeLocker{Style.RESET_ALL}")
                    input("\nPress Enter to continue...")

            except Exception as e:
                print(f"{Fore.RED}Error setting up account: {e}{Style.RESET_ALL}")
                input("\nPress Enter to continue...")

        elif choice == '7':
            # Export configuration
            config_json = account_manager.export_config()
            print(f"\n{Fore.CYAN}Configuration JSON:{Style.RESET_ALL}")
            print(config_json)
            input("\nPress Enter to continue...")

        elif choice == '8':
            # Back to main menu
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

        if choice == '4':
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

        elif choice == '3':
            await handle_account_channel_configuration()

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
