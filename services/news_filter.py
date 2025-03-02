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
                logger.info(f"Loaded economic calendar from cache with {len(self.news_events)} events")
            except Exception as e:
                logger.error(f"Error loading calendar from cache: {e}")

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

    from pytz import timezone
    import pytz

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
                    print(f"Skipping row due to error: {e}")

            self.news_events.sort(key=lambda x: x['datetime'])

        except Exception as e:
            logger.error(f"Error parsing calendar CSV: {e}", exc_info=True)

    def get_events_by_filter(self, filter_type: str):
        """Get events based on the selected filter (today, this week, or next N hours)."""
        now = datetime.now(pytz.UTC)

        if filter_type == "today":
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=1)
        elif filter_type == "week":
            start_time = now - timedelta(days=now.weekday())  # Monday of the current week
            end_time = start_time + timedelta(days=7)
        else:  # Default: Next N hours
            hours = int(filter_type.split()[1])  # Extract hours from "next N hours"
            start_time = now
            end_time = now + timedelta(hours=hours)

        filtered_events = [
            event for event in self.news_events
            if start_time <= event['datetime'] <= end_time
        ]

        return filtered_events

    def get_upcoming_high_impact_events(self, hours: int = 24):
        """Get a list of upcoming high-impact news events."""
        now = datetime.now(pytz.UTC)
        cutoff = now + timedelta(hours=hours)
        return [event for event in self.news_events if now <= event['datetime'] <= cutoff]
