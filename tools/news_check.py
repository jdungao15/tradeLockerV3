#!/usr/bin/env python
"""
News Event Filter Testing Tool

Usage:
    python news_check.py list --today --impact high     # List today's high-impact events only
    python news_check.py list --week --impact all       # List all events this week
    python news_check.py list --hours 168 --sort-impact # List events for next 7 days sorted by impact
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
    impact_lower = impact.lower() if impact else ""
    if impact_lower == "high":
        return Fore.RED + "High" + Style.RESET_ALL
    elif impact_lower == "medium":
        return Fore.YELLOW + "Medium" + Style.RESET_ALL
    elif impact_lower == "low":
        return Fore.GREEN + "Low" + Style.RESET_ALL
    return impact.capitalize() if impact else "N/A"


def filter_by_impact(events, impact_level=None):
    """Filter events by impact level"""
    if not impact_level or impact_level.lower() == 'all':
        return events

    # Convert to lowercase for case-insensitive comparison
    impact_level = impact_level.lower()
    return [event for event in events if event.get('impact', '').lower() == impact_level]


def sort_events_by_impact(events):
    """Sort events by impact level (High > Medium > Low)"""
    impact_priority = {"high": 1, "medium": 2, "low": 3}
    return sorted(events, key=lambda e: impact_priority.get(e.get('impact', '').lower(), 4))


def sort_events_by_datetime(events):
    """Sort events by datetime"""
    return sorted(events, key=lambda e: e['datetime'])


async def display_events(news_filter, time_filter, summary=False, impact_level=None, sort_by_impact=False):
    """Display economic events based on time filter with optional filtering and sorting"""
    # Get all events for the time period
    upcoming_events = news_filter.get_events_by_filter(time_filter)

    if not upcoming_events:
        print(f"{Fore.YELLOW}No economic events found for {time_filter}.{Style.RESET_ALL}")
        return

    # Filter by impact level if specified
    if impact_level and impact_level.lower() != 'all':
        filtered_events = filter_by_impact(upcoming_events, impact_level)
        if not filtered_events:
            print(f"{Fore.YELLOW}No {impact_level.upper()} impact events found for {time_filter}.{Style.RESET_ALL}")
            return
        upcoming_events = filtered_events

    # Sort events
    if sort_by_impact:
        upcoming_events = sort_events_by_impact(upcoming_events)
    else:
        upcoming_events = sort_events_by_datetime(upcoming_events)

    # Display title with impact level if filtered
    title = f"Economic Events: {time_filter}"
    if impact_level and impact_level.lower() != 'all':
        title += f" ({impact_level.upper()} Impact Only)"

    print(f"\n{Fore.CYAN}=== {title} ==={Style.RESET_ALL}\n")
    print(f"Total events: {len(upcoming_events)}\n")

    if summary:
        headers = ["Country", "Impact"]
        table_data = []
        for event in upcoming_events:
            table_data.append([
                event['currency'],
                colorize_impact(event.get('impact', 'N/A'))
            ])
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
    parser.add_argument('--sort-impact', action='store_true', help='Sort events by impact level')
    parser.add_argument('--impact', choices=['high', 'medium', 'low', 'all'],
                        help='Filter by impact level (high, medium, low, or all)')
    parser.add_argument('--debug', action='store_true', help='Show debug information')

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize the news filter
    news_filter = NewsEventFilter()
    await news_filter.initialize()

    # Determine the time filter
    if args.today:
        time_filter = "today"
    elif args.week:
        time_filter = "week"
    else:
        time_filter = f"next {args.hours} hours"

    # Impact level - if not specified but using the old --impact flag, default to sorting by impact
    impact_level = args.impact
    if impact_level is None and args.sort_impact:
        impact_level = 'all'

    # Display events with the appropriate filters
    await display_events(
        news_filter=news_filter,
        time_filter=time_filter,
        summary=args.summary,
        impact_level=impact_level,
        sort_by_impact=args.sort_impact
    )

    if args.debug:
        # Show some debug information about the filter results
        all_events = news_filter.get_events_by_filter(time_filter)
        high_events = [e for e in all_events if e.get('impact', '').lower() == 'high']
        medium_events = [e for e in all_events if e.get('impact', '').lower() == 'medium']
        low_events = [e for e in all_events if e.get('impact', '').lower() == 'low']

        print(f"\n{Fore.CYAN}=== Debug Information ==={Style.RESET_ALL}")
        print(f"Total events: {len(all_events)}")
        print(f"High impact: {len(high_events)}")
        print(f"Medium impact: {len(medium_events)}")
        print(f"Low impact: {len(low_events)}")
        print(f"Other/Unknown impact: {len(all_events) - len(high_events) - len(medium_events) - len(low_events)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)