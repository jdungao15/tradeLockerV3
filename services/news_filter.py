import csv
import asyncio
import aiohttp
import logging
import os
from io import StringIO
from datetime import datetime, timedelta
from pytz import timezone
import pytz

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
        self.calendar_cache_path = "economic_events.csv"

    async def initialize(self):
        """Initialize by downloading the news calendar."""
        if os.path.exists(self.calendar_cache_path):
            try:
                with open(self.calendar_cache_path, 'r') as cache_file:
                    await self._parse_calendar(cache_file.read())
                self.last_update = datetime.fromtimestamp(os.path.getmtime(self.calendar_cache_path))
                # Silent - calendar loaded
            except Exception as e:
                logger.error(f"❌ Error loading calendar from cache: {e}")

        if not self.news_events or not self.last_update or datetime.now() - self.last_update > self.update_interval:
            await self.update_calendar()

    async def update_calendar(self, force: bool = False) -> bool:
        """Update the economic calendar by downloading the latest data."""
        async with self._update_lock:
            if not force and self.last_update and datetime.now() - self.last_update < self.update_interval:
                return True

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.calendar_url) as response:
                        if response.status != 200:
                            logger.error(f"Failed to download calendar: HTTP {response.status}")
                            return False
                        content = await response.text()

                        with open(self.calendar_cache_path, 'w') as cache_file:
                            cache_file.write(content)

                await self._parse_calendar(content)
                self.last_update = datetime.now()
                return True

            except Exception as e:
                logger.error(f"Error updating calendar: {e}", exc_info=True)
                return False

    async def _parse_calendar(self, csv_content: str):
        """Parse the CSV content and convert event times from UTC to LOCAL timezone."""
        try:
            self.news_events = []
            csv_file = StringIO(csv_content)
            reader = csv.DictReader(csv_file)

            utc_timezone = timezone("UTC")  # CSV is in UTC
            local_timezone = timezone("America/New_York")  # Your correct local timezone

            for row in reader:
                try:
                    title = row.get('Title', '').strip()
                    country = row.get('Country', '').strip()
                    date_str = row.get('Date', '').strip()
                    time_str = row.get('Time', '').strip()
                    impact = row.get('Impact', '').strip().capitalize()
                    forecast = row.get('Forecast', 'N/A').strip()
                    previous = row.get('Previous', 'N/A').strip()

                    if not title or not country:
                        continue

                    # Convert date and time
                    event_date = datetime.strptime(date_str, '%m-%d-%Y')

                    if time_str not in ["All Day", "Tentative"]:
                        event_time = datetime.strptime(time_str, '%I:%M%p').time()
                    else:
                        event_time = datetime.min.time()  # Default to start of day

                    # Combine into a full datetime object
                    event_datetime = datetime.combine(event_date, event_time)

                    # CSV is already in UTC, so we directly localize it
                    event_datetime = utc_timezone.localize(event_datetime).astimezone(local_timezone)

                    # Debug: Print after Local Time conversion

                    self.news_events.append({
                        'datetime': event_datetime,
                        'currency': country,
                        'impact': impact,
                        'event': title,
                        'forecast': forecast,
                        'previous': previous
                    })

                except Exception as e:
                    logger.error(f"Skipping row due to error: {e}")

            self.news_events.sort(key=lambda x: x['datetime'])

        except Exception as e:
            logger.error(f"Error parsing calendar CSV: {e}", exc_info=True)

    def get_events_by_filter(self, filter_type: str):
        """
        Get events based on the selected filter (today, this week, or next N hours).

        Args:
            filter_type: String indicating what time period to filter for:
                         "today", "week", or "next X hours"

        Returns:
            List of events matching the filter criteria
        """
        now = datetime.now(pytz.UTC)

        if filter_type == "today":
            # Get today's events (local timezone)
            local_now = now.astimezone(self.local_timezone)
            start_time = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=1)

            # Convert back to UTC for comparison with events
            start_time = start_time.astimezone(pytz.UTC)
            end_time = end_time.astimezone(pytz.UTC)

        elif filter_type == "week":
            # Get events for the current week (Monday to Sunday)
            local_now = now.astimezone(self.local_timezone)

            # Calculate the start of the week (Monday)
            start_time = local_now - timedelta(days=local_now.weekday())
            start_time = start_time.replace(hour=0, minute=0, second=0, microsecond=0)

            # End of week (Sunday)
            end_time = start_time + timedelta(days=7)

            # Convert back to UTC for comparison
            start_time = start_time.astimezone(pytz.UTC)
            end_time = end_time.astimezone(pytz.UTC)

            # Debug logging
            logger.debug(f"Week filter: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}")

        else:  # Default: Next N hours
            # Extract hours from filter_type (format: "next X hours")
            try:
                hours = int(filter_type.split()[1])
            except (IndexError, ValueError):
                hours = 24  # Default to 24 hours if parsing fails

            start_time = now
            end_time = now + timedelta(hours=hours)

        # Filter events based on the calculated time window
        filtered_events = []
        for event in self.news_events:
            event_time = event['datetime']

            # Convert event time to UTC for proper comparison
            if event_time.tzinfo != pytz.UTC:
                event_time = event_time.astimezone(pytz.UTC)

            if start_time <= event_time <= end_time:
                filtered_events.append(event)

        logger.info(f"Filter '{filter_type}' returned {len(filtered_events)} events")
        return filtered_events

    def get_upcoming_high_impact_events(self, hours: int = 24):
        """Get a list of upcoming high-impact news events."""
        now = datetime.now(pytz.UTC)
        cutoff = now + timedelta(hours=hours)

        high_impact_events = [
            event for event in self.news_events
            if now <= event['datetime'] <= cutoff and
            event.get('impact', '').lower() == 'high'
        ]

        return high_impact_events

    def get_high_impact_events_for_currencies(self, currencies, hours=24):
        """
        Get high-impact news events for specific currencies within the next X hours.

        Args:
            currencies: List of currency codes to check (e.g., ['USD', 'EUR'])
            hours: Number of hours to look ahead

        Returns:
            list: Filtered list of high-impact news events
        """
        if not self.news_events:
            return []

        # Convert all currencies to uppercase for comparison
        currencies = [c.upper() for c in currencies]

        # Current time and future cutoff
        now = datetime.now(pytz.UTC)
        cutoff = now + timedelta(hours=hours)

        # Filter events by impact, currency, and time
        filtered_events = []

        for event in self.news_events:
            event_time = event['datetime']
            event_currency = event.get('currency', '').upper()
            event_impact = event.get('impact', '').lower()

            # Check if this is a high-impact event
            if event_impact != 'high':
                continue

            # Check if the event is for one of our currencies of interest
            if event_currency not in currencies and event_currency != 'ALL':
                continue

            # Check if the event is within our time window
            if now <= event_time <= cutoff:
                filtered_events.append(event)

        # Sort events by time
        filtered_events.sort(key=lambda x: x['datetime'])

        return filtered_events

    def can_place_order(self, parsed_signal, current_time):
        """
        Check if an order can be placed based on economic news events.
        Implements PropFirm rule 2.5.2 regarding high-impact news events.

        Args:
            parsed_signal: The parsed trading signal with instrument information
            current_time: Current time for comparison with news events

        Returns:
            tuple: (can_trade, reason) where can_trade is a boolean and reason is a string
        """
        # Default to allowing trades if news filtering is disabled
        if not hasattr(self, 'news_events') or not self.news_events:
            return True, "No news events loaded"

        # Extract the currency from the instrument (e.g., 'EURUSD' -> 'EUR' and 'USD')
        instrument = parsed_signal.get('instrument', '')

        # For forex pairs, extract both currencies
        currencies = []
        if len(instrument) == 6 and instrument.isalpha():  # Standard forex pair like EURUSD
            currencies.append(instrument[:3])  # Base currency
            currencies.append(instrument[3:])  # Quote currency
        elif instrument in ['XAUUSD', 'XAGUSD']:  # Gold and Silver
            currencies.append('USD')  # Only affected by USD news
        elif instrument in ['DJI30', 'NDX100']:  # US indices
            currencies.append('USD')  # US indices affected by USD news

        # Convert to uppercase for comparison
        currencies = [c.upper() for c in currencies]

        # Check for high-impact news in the next few hours (propfirm rule 2.5.2)
        # Typically 30 min before and after high-impact news events
        window_before = 6  # minutes before the event
        window_after = 6  # minutes after the event

        # Time windows for comparison
        start_window = current_time - timedelta(minutes=window_before)
        end_window = current_time + timedelta(minutes=window_after)

        # Check all news events
        for event in self.news_events:
            event_time = event['datetime']
            event_currency = event.get('currency', '').upper()
            event_impact = event.get('impact', '').lower()

            # Only check for HIGH impact events
            if event_impact != 'high':
                continue

            # Check if the event affects our trading instrument
            if event_currency not in currencies and event_currency != 'ALL':
                continue

            # Check if the event is within our time window
            if start_window <= event_time <= end_window:
                reason = f"High-impact {event_currency} news '{event['event']}' at {event_time.strftime('%H:%M:%S')}"
                return False, reason

        # No high-impact news found within the window
        return True, "No conflicting high-impact news events"
