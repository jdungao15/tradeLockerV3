#!/usr/bin/env python
"""
News Event Filter Testing Tool

This script allows you to check upcoming high-impact economic events
and test if trading is allowed for specific instruments.

Usage:
    python news_check.py list              # List upcoming high-impact news events
    python news_check.py check EURUSD      # Check if trading is allowed for EURUSD
    python news_check.py check XAUUSD      # Check if trading is allowed for Gold
    python news_check.py check all         # Check all major instruments
"""

import os
import sys
import asyncio
import logging
import argparse
from datetime import datetime, timedelta
import pytz
from colorama import init, Fore, Style

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

# List of major instruments to check
MAJOR_INSTRUMENTS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "EURJPY", "EURGBP", "GBPJPY", "XAUUSD", "DJI30", "NDX100"
]


async def display_upcoming_events(news_filter, hours=24):
    """Display upcoming high-impact news events"""
    upcoming_events = news_filter.get_upcoming_high_impact_events(hours=hours)

    if not upcoming_events:
        print(f"{Fore.YELLOW}No upcoming high-impact news events in the next {hours} hours.{Style.RESET_ALL}")
        return

    print(f"\n{Fore.CYAN}=== Upcoming High-Impact News Events (next {hours} hours) ==={Style.RESET_ALL}")
    print(f"{'Time (UTC)':^20} | {'Currency':^8} | {'Event':^50}")
    print("-" * 82)

    for event in upcoming_events:
        event_time = event['datetime']
        time_str = event_time.strftime('%Y-%m-%d %H:%M')
        print(f"{time_str:^20} | {event['currency']:^8} | {event['event'][:50]}")


async def check_instrument(news_filter, instrument, current_time=None):
    """Check if trading is allowed for a specific instrument"""
    if not current_time:
        current_time = datetime.now(pytz.UTC)

    is_restricted, event_info = news_filter.is_trading_restricted(instrument, current_time)

    if is_restricted:
        event = event_info['event']
        event_time = event['datetime']
        time_diff = event_time - current_time if event_time > current_time else current_time - event_time
        time_diff_minutes = abs(time_diff.total_seconds() / 60)

        print(f"{Fore.RED}✘ {instrument}: Trading restricted{Style.RESET_ALL}")
        print(f"  Reason: {event['currency']} high-impact news event: {event['event']}")
        print(f"  Time: {event_time.strftime('%Y-%m-%d %H:%M UTC')}")
        print(
            f"  {Fore.YELLOW}{'Upcoming' if event_time > current_time else 'Recent'} event, {time_diff_minutes:.1f} minutes {('until' if event_time > current_time else 'ago')}{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}✓ {instrument}: Trading allowed{Style.RESET_ALL}")


async def check_all_instruments(news_filter):
    """Check trading status for all major instruments"""
    current_time = datetime.now(pytz.UTC)

    print(f"\n{Fore.CYAN}=== Trading Status for Major Instruments ==={Style.RESET_ALL}")
    for instrument in MAJOR_INSTRUMENTS:
        await check_instrument(news_filter, instrument, current_time)
        await asyncio.sleep(0.1)  # Small delay for better readability


async def main():
    parser = argparse.ArgumentParser(description="Economic News Event Filter Tool")
    parser.add_argument('action', choices=['list', 'check'], help='Action to perform')
    parser.add_argument('instrument', nargs='?', default='all', help='Instrument to check (or "all")')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look ahead for news events')

    args = parser.parse_args()

    # Initialize the news filter
    news_filter = NewsEventFilter()
    await news_filter.initialize()

    if args.action == 'list':
        await display_upcoming_events(news_filter, hours=args.hours)
    elif args.action == 'check':
        if args.instrument.lower() == 'all':
            await check_all_instruments(news_filter)
        else:
            instrument = args.instrument.upper()
            print(f"\n{Fore.CYAN}=== Trading Status for {instrument} ==={Style.RESET_ALL}")
            await check_instrument(news_filter, instrument)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)