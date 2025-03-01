import csv
import asyncio
import aiohttp
import logging
import pytz
import os
from io import StringIO
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class NewsEventFilter:
    """
    Class to handle economic news events and determine trading restrictions.
    Implements PropFirm trading rule 2.5.2 regarding high-impact news events.
    """

    def __init__(self,
                 calendar_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.csv",
                 timezone: str = "America/New_York"):
        """
        Initialize the news event filter.

        Args:
            calendar_url: URL to download the economic calendar CSV
            timezone: Local timezone for time conversions
        """
        self.calendar_url = calendar_url
        self.local_timezone = pytz.timezone(timezone)
        self.news_events = []
        self.last_update = None
        self._update_lock = asyncio.Lock()
        self.update_interval = timedelta(hours=6)  # Update calendar every 6 hours

        # Currency mappings to match trading pairs
        self.currency_mappings = {
            "USD": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "XAUUSD", "DJI30"],
            "EUR": ["EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD"],
            "GBP": ["GBPUSD", "EURGBP", "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD"],
            "JPY": ["USDJPY", "EURJPY", "GBPJPY", "CHFJPY", "AUDJPY", "NZDJPY", "CADJPY"],
            "AUD": ["AUDUSD", "EURAUD", "GBPAUD", "AUDJPY", "AUDCHF", "AUDNZD", "AUDCAD"],
            "NZD": ["NZDUSD", "EURNZD", "GBPNZD", "NZDJPY", "NZDCHF", "AUDNZD", "NZDCAD"],
            "CAD": ["USDCAD", "EURCAD", "GBPCAD", "CADJPY", "CADCHF", "AUDCAD", "NZDCAD"],
            "CHF": ["USDCHF", "EURCHF", "GBPCHF", "CHFJPY", "AUDCHF", "NZDCHF", "CADCHF"]
        }

        # Path to save calendar locally
        self.calendar_cache_path = "economic_events.csv"

    async def initialize(self):
        """Initialize by downloading the news calendar."""
        # Try to load from cache first
        if os.path.exists(self.calendar_cache_path):
            try:
                with open(self.calendar_cache_path, 'r') as cache_file:
                    await self._parse_calendar(cache_file.read())
                self.last_update = datetime.fromtimestamp(os.path.getmtime(self.calendar_cache_path))
                logger.info(f"Loaded economic calendar from cache with {len(self.news_events)} events")
            except Exception as e:
                logger.error(f"Error loading calendar from cache: {e}")

        # Update from online source if needed
        if not self.news_events or not self.last_update or \
                datetime.now() - self.last_update > self.update_interval:
            await self.update_calendar()

    async def update_calendar(self, force: bool = False) -> bool:
        """
        Update the economic calendar by downloading the latest data.

        Args:
            force: Force update even if the last update was recent

        Returns:
            bool: True if update was successful, False otherwise
        """
        async with self._update_lock:
            # Check if update is needed
            if not force and self.last_update and \
                    datetime.now() - self.last_update < self.update_interval:
                logger.debug("Calendar was recently updated, skipping update")
                return True

            try:
                logger.info("Updating economic calendar...")

                async with aiohttp.ClientSession() as session:
                    async with session.get(self.calendar_url) as response:
                        if response.status != 200:
                            logger.error(f"Failed to download calendar: HTTP {response.status}")
                            return False

                        content = await response.text()

                        # Save to cache file
                        try:
                            with open(self.calendar_cache_path, 'w') as cache_file:
                                cache_file.write(content)
                        except Exception as e:
                            logger.error(f"Could not save calendar to cache: {e}")

                # Parse CSV content
                await self._parse_calendar(content)
                self.last_update = datetime.now()
                logger.info(f"Economic calendar updated with {len(self.news_events)} events")
                return True

            except Exception as e:
                logger.error(f"Error updating calendar: {e}", exc_info=True)
                return False

    async def _parse_calendar(self, csv_content: str):
        """
        Parse the CSV content from ForexFactory calendar.

        Args:
            csv_content: CSV content as string
        """
        try:
            # Reset news events
            self.news_events = []

            # Parse CSV
            csv_file = StringIO(csv_content)
            reader = csv.DictReader(csv_file)

            # Current date for handling date format in CSV
            current_date = None

            for row in reader:
                try:
                    # Extract data from row
                    date_str = row.get('Date', '').strip()
                    time_str = row.get('Time', '').strip()
                    currency = row.get('Currency', '').strip()
                    impact = row.get('Impact', '').strip().lower()
                    event = row.get('Event', '').strip()

                    # Skip if no currency affected (some rows might be headers or empty)
                    if not currency:
                        continue

                    # Skip if not high impact
                    # ForexFactory uses red color (high), orange (medium), yellow (low)
                    if 'high' not in impact:
                        continue

                    # Handle date (FF calendar uses empty dates for same day events)
                    if date_str:
                        try:
                            # Parse date like "Mon Dec 18"
                            current_date = datetime.strptime(date_str, '%a %b %d')
                            # Add current year since it's not in the string
                            current_date = current_date.replace(year=datetime.now().year)
                        except ValueError:
                            logger.warning(f"Could not parse date: {date_str}")
                            continue

                    if not current_date:
                        logger.warning("No current date established, skipping event")
                        continue

                    # Parse time if available (some events don't have a specific time)
                    event_datetime = None
                    if time_str and time_str != "All Day" and time_str != "Tentative":
                        try:
                            # Parse time like "8:30am" or "12:30pm"
                            time_obj = datetime.strptime(time_str, '%I:%M%p').time()
                            event_datetime = datetime.combine(current_date.date(), time_obj)

                            # Convert to UTC
                            local_dt = self.local_timezone.localize(event_datetime)
                            event_datetime = local_dt.astimezone(pytz.UTC)
                        except ValueError:
                            logger.warning(f"Could not parse time: {time_str}")
                            # Use start of day if time can't be parsed
                            event_datetime = datetime.combine(current_date.date(),
                                                              datetime.min.time())
                            event_datetime = self.local_timezone.localize(event_datetime).astimezone(pytz.UTC)
                    else:
                        # For "All Day" or "Tentative" events, set to start of day
                        event_datetime = datetime.combine(current_date.date(),
                                                          datetime.min.time())
                        event_datetime = self.local_timezone.localize(event_datetime).astimezone(pytz.UTC)

                    # Add to news events list
                    self.news_events.append({
                        'datetime': event_datetime,
                        'currency': currency,
                        'impact': impact,
                        'event': event
                    })

                except Exception as e:
                    logger.warning(f"Error parsing row: {e}")
                    continue

            # Sort events by datetime
            self.news_events.sort(key=lambda x: x['datetime'] if x['datetime'] else datetime.max)

        except Exception as e:
            logger.error(f"Error parsing calendar CSV: {e}", exc_info=True)
            raise

    def is_trading_restricted(self, instrument: str, current_time: Optional[datetime] = None) -> Tuple[
        bool, Optional[Dict[str, Any]]]:
        """
        Check if trading is restricted for the given instrument at the current time.

        Implements PropFirm rule 2.5.2:
        - No trading 5 minutes before and after high impact news on affected currency
        - Exception: Trades opened 5 hours prior to news event are allowed

        Args:
            instrument: Trading instrument (e.g., "EURUSD")
            current_time: Current time (defaults to now if not provided)

        Returns:
            Tuple[bool, Optional[Dict]]: (is_restricted, restricting_event_info)
        """
        if not current_time:
            current_time = datetime.now(pytz.UTC)

        # Normalize instrument name
        instrument = instrument.upper()

        # Extract currencies from the instrument
        currencies = self._extract_currencies(instrument)
        if not currencies:
            logger.warning(f"Could not extract currencies from instrument: {instrument}")
            return False, None

        # Check against each news event
        for event in self.news_events:
            event_currency = event['currency']
            event_time = event['datetime']

            # Skip if event time is None or event currency doesn't affect this instrument
            if not event_time or event_currency not in currencies:
                continue

            # Calculate time differences
            time_until_event = event_time - current_time
            time_since_event = current_time - event_time

            # Check if within restricted window (5 minutes before to 5 minutes after)
            if time_until_event >= timedelta(0) and time_until_event <= timedelta(minutes=5):
                # Upcoming event within 5-minute window
                return True, {
                    'event': event,
                    'reason': f"Upcoming high-impact news for {event_currency} in {time_until_event}"
                }

            if time_since_event >= timedelta(0) and time_since_event <= timedelta(minutes=5):
                # Recent event within 5-minute window
                return True, {
                    'event': event,
                    'reason': f"Recent high-impact news for {event_currency} {time_since_event} ago"
                }

        return False, None

    def can_place_order(self, parsed_signal: dict, current_time: Optional[datetime] = None) -> Tuple[
        bool, Optional[str]]:
        """
        Check if an order can be placed based on the signal and news restrictions.

        Args:
            parsed_signal: Parsed trading signal with instrument, entry_point, etc.
            current_time: Current time (defaults to now)

        Returns:
            Tuple[bool, Optional[str]]: (can_place_order, reason_if_restricted)
        """
        if not current_time:
            current_time = datetime.now(pytz.UTC)

        instrument = parsed_signal.get('instrument')
        if not instrument:
            return False, "No instrument specified in signal"

        is_restricted, event_info = self.is_trading_restricted(instrument, current_time)

        if is_restricted and event_info:
            event_data = event_info['event']
            return False, (f"Trading restricted due to high-impact {event_data['currency']} "
                           f"news: {event_data['event']} at {event_data['datetime'].strftime('%H:%M UTC')}")

        return True, None

    def _extract_currencies(self, instrument: str) -> List[str]:
        """
        Extract the currencies involved in an instrument.

        Args:
            instrument: Instrument name like "EURUSD" or "DJI30"

        Returns:
            List[str]: List of currency codes
        """
        # Special cases
        if instrument == "XAUUSD":
            return ["USD"]  # Gold is mainly affected by USD
        elif instrument == "DJI30":
            return ["USD"]  # Dow Jones is affected by USD
        elif instrument == "NDX100":
            return ["USD"]  # NASDAQ is affected by USD

        # For regular forex pairs
        affected_currencies = []
        for currency, pairs in self.currency_mappings.items():
            if instrument in pairs:
                affected_currencies.append(currency)

        # If we couldn't find it in mappings, try to extract from name (e.g., EURUSD -> EUR, USD)
        if not affected_currencies and len(instrument) == 6:
            base_currency = instrument[:3]
            quote_currency = instrument[3:]
            if base_currency in self.currency_mappings:
                affected_currencies.append(base_currency)
            if quote_currency in self.currency_mappings:
                affected_currencies.append(quote_currency)

        return affected_currencies

    def get_upcoming_high_impact_events(self, hours: int = 24) -> List[Dict]:
        """
        Get a list of upcoming high-impact news events.

        Args:
            hours: Number of hours to look ahead

        Returns:
            List[Dict]: List of upcoming high-impact events
        """
        now = datetime.now(pytz.UTC)
        cutoff = now + timedelta(hours=hours)

        upcoming_events = []
        for event in self.news_events:
            event_time = event['datetime']
            if event_time and now <= event_time <= cutoff:
                upcoming_events.append(event)

        return upcoming_events

    def is_five_hours_prior_exception(self, instrument: str, order_time: datetime,
                                      current_time: Optional[datetime] = None) -> bool:
        """
        Check if the trade qualifies for the 5-hour prior exception.

        According to PropFirm rule 2.5.2, trades opened 5 hours prior to a news event
        are exempt from the news trading restriction.

        Args:
            instrument: The trading instrument
            order_time: When the order was originally placed
            current_time: Current time (defaults to now)

        Returns:
            bool: True if the trade qualifies for the exception
        """
        if not current_time:
            current_time = datetime.now(pytz.UTC)

        # Extract currencies affected by this instrument
        currencies = self._extract_currencies(instrument)
        if not currencies:
            return False

        # Check if the order was placed at least 5 hours before any high-impact news events
        for event in self.news_events:
            if event['currency'] not in currencies:
                continue

            event_time = event['datetime']
            if not event_time:
                continue

            # If current time is within 5 minutes after event
            time_since_event = current_time - event_time
            if 0 <= time_since_event.total_seconds() <= 300:  # 5 minutes = 300 seconds
                # Check if order was placed at least 5 hours before the event
                time_before_event = event_time - order_time
                if time_before_event.total_seconds() >= 18000:  # 5 hours = 18000 seconds
                    return True

        return False