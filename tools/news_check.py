#!/usr/bin/env python
"""
News Event Filter Testing Tool

Usage:
    python news_check.py list --today --impact  # List today's events sorted by impact
    python news_check.py list --week --summary  # List all events this week (Country & Impact only)
    python news_check.py list --hours 48        # List events in the next 48 hours
"""

import os
import sys
import asyncio
import logging
import argparse
from datetime import datetime, timedelta
import pytz
from colorama import init, Fore, Style
from tabulate import tabulate

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the NewsEventFilter
from services.news_filter import NewsEventFilter

# Initialize colorama
init(autoreset=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('news_check')


def colorize_impact(impact):
    """Returns a colorized version of the impact level"""
    if impact.lower() == "high":
        return Fore.RED + impact.capitalize() + Style.RESET_ALL
    elif impact.lower() == "medium":
        return Fore.YELLOW + impact.capitalize() + Style.RESET_ALL
    elif impact.lower() == "low":
        return Fore.GREEN + impact.capitalize() + Style.RESET_ALL
    return impact.capitalize()


def sort_events(events, sort_by_impact=False):
    """Sort events by impact level if specified"""
    impact_priority = {"High": 1, "Medium": 2, "Low": 3}
    if sort_by_impact:
        return sorted(events, key=lambda e: impact_priority.get(e.get('impact', 'Low'), 3))
    return events


async def display_events(news_filter, time_filter, summary=False, sort_by_impact=False):
    """Display economic events based on time filter with optional sorting"""
    upcoming_events = news_filter.get_events_by_filter(time_filter)

    if not upcoming_events:
        print(f"{Fore.YELLOW}No economic events found for {time_filter}.{Style.RESET_ALL}")
        return

    # Sort events if --impact flag is used
    upcoming_events = sort_events(upcoming_events, sort_by_impact)

    print(f"\n{Fore.CYAN}=== Economic Events: {time_filter} ==={Style.RESET_ALL}\n")

    if summary:
        headers = ["Country", "Impact"]
        table_data = []
        for event in upcoming_events:
            table_data.append([event['currency'], colorize_impact(event.get('impact', 'N/A'))])
    else:
        headers = ["Title", "Country", "Date", "Time", "Impact", "Forecast", "Previous"]
        table_data = []
        for event in upcoming_events:
            event_time = event['datetime']
            date_str = event_time.strftime('%m-%d-%Y')
            time_str = event_time.strftime('%I:%M%p')

            table_data.append([
                event['event'][:50],
                event['currency'],
                date_str,
                time_str,
                colorize_impact(event.get('impact', 'N/A')),
                event.get('forecast', 'N/A'),
                event.get('previous', 'N/A')
            ])

    print(tabulate(table_data, headers=headers, tablefmt="github"))


async def main():
    parser = argparse.ArgumentParser(description="Economic News Event Filter Tool")
    parser.add_argument('action', choices=['list'], help='Action to perform')
    parser.add_argument('--today', action='store_true', help='List events happening today')
    parser.add_argument('--week', action='store_true', help='List all events this week')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look ahead for news events')
    parser.add_argument('--summary', action='store_true', help='Show only Country & Impact')
    parser.add_argument('--impact', action='store_true', help='Sort events by impact level')

    args = parser.parse_args()

    # Initialize the news filter
    news_filter = NewsEventFilter()
    await news_filter.initialize()

    if args.today:
        await display_events(news_filter, "today", args.summary, args.impact)
    elif args.week:
        await display_events(news_filter, "week", args.summary, args.impact)
    else:
        await display_events(news_filter, f"next {args.hours} hours", args.summary, args.impact)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
