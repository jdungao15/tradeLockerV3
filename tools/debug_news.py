#!/usr/bin/env python
"""
Debug script to analyze economic events CSV and identify date filtering issues
"""

import csv
import sys
import os
from datetime import datetime
import pytz


def debug_csv_dates(csv_path):
    """
    Analyze dates in the CSV file and print distribution by day
    """
    print(f"Analyzing CSV file: {csv_path}")

    # Count events by date
    date_counts = {}
    unique_dates = set()

    try:
        with open(csv_path, 'r', encoding='utf-8') as file:
            # Skip header row
            reader = csv.DictReader(file)

            for row in reader:
                date_str = row.get('Date', '').strip()
                impact = row.get('Impact', '').strip()

                if date_str:
                    # Add to date counts
                    if date_str not in date_counts:
                        date_counts[date_str] = {'high': 0, 'medium': 0, 'low': 0, 'total': 0}

                    date_counts[date_str]['total'] += 1

                    # Count by impact
                    impact_lower = impact.lower()
                    if impact_lower == 'high':
                        date_counts[date_str]['high'] += 1
                    elif impact_lower == 'medium':
                        date_counts[date_str]['medium'] += 1
                    elif impact_lower == 'low':
                        date_counts[date_str]['low'] += 1

                    unique_dates.add(date_str)

        # Report findings
        print(f"\nFound {len(unique_dates)} unique dates in the CSV")
        print("\nEvent distribution by date:")
        print("-" * 60)
        print(f"{'Date':<12} {'Total':<8} {'High':<8} {'Medium':<8} {'Low':<8}")
        print("-" * 60)

        for date_str in sorted(date_counts.keys()):
            counts = date_counts[date_str]
            print(f"{date_str:<12} {counts['total']:<8} {counts['high']:<8} {counts['medium']:<8} {counts['low']:<8}")

        # Check date format consistency
        print("\nChecking date format consistency...")
        date_formats = {}

        for date_str in unique_dates:
            try:
                parsed_date = datetime.strptime(date_str, '%m-%d-%Y')
                format_str = '%m-%d-%Y'
            except ValueError:
                try:
                    parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                    format_str = '%Y-%m-%d'
                except ValueError:
                    format_str = 'unknown'

            if format_str not in date_formats:
                date_formats[format_str] = []
            date_formats[format_str].append(date_str)

        for format_str, dates in date_formats.items():
            print(f"Format {format_str}: {len(dates)} dates")
            if format_str == 'unknown':
                print(f"  Examples of unknown formats: {dates[:5]}")

    except Exception as e:
        print(f"Error analyzing CSV: {e}")


if __name__ == "__main__":
    csv_path = "economic_events.csv"
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]

    debug_csv_dates(csv_path)