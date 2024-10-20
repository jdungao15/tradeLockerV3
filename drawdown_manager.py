import json
import os
import threading
from datetime import datetime, timedelta
import pytz

# Global variables
max_drawdown_balance = 0  # This is the minimum balance the account should not drop below
drawdown_limit_file = 'daily_drawdown.json'
starting_balance = 0  # Balance at the start of the trading day


# Function to load drawdown data
def load_drawdown_data(selected_account):
    global max_drawdown_balance, starting_balance
    if os.path.exists(drawdown_limit_file):
        with open(drawdown_limit_file, 'r') as file:
            data = json.load(file)
            max_drawdown_balance = data.get('max_drawdown_balance', 0)
            starting_balance = data.get('starting_balance', 0)
    else:
        reset_daily_drawdown(selected_account)


# Function to save drawdown data
def save_drawdown_data():
    # Delete the old file if it exists to ensure a fresh save
    if os.path.exists(drawdown_limit_file):
        os.remove(drawdown_limit_file)

    # Now save the updated data
    with open(drawdown_limit_file, 'w') as file:
        json.dump({
            'max_drawdown_balance': max_drawdown_balance,
            'starting_balance': starting_balance
        }, file)


# Function to determine the correct tier size and apply the 10% rule
def get_tier_size(account_balance):
    if account_balance <= 9000:
        return 5000, 9000  # $5,000 tier, max balance is $9,000
    elif account_balance <= 22500:
        return 10000, 22500  # $10,000 tier, max balance is $22,500
    elif account_balance <= 45000:
        return 25000, 45000  # $25,000 tier, max balance is $45,000
    elif account_balance <= 90000:
        return 50000, 90000  # $50,000 tier, max balance is $90,000
    else:
        return 100000, float('inf')  # $100,000 tier, no upper limit


# Function to reset the daily drawdown at 6 PM EST
def reset_daily_drawdown(selected_account):
    global max_drawdown_balance, starting_balance
    # Get the latest balance
    account_balance = float(selected_account['accountBalance'])

    # Determine the correct tier size and its upper limit
    tier_size, upper_limit = get_tier_size(account_balance)

    # The drawdown is based on the tier, so calculate 4% of the tier size
    drawdown_limit = tier_size * 0.04

    # Set the starting balance and max drawdown balance
    starting_balance = account_balance
    max_drawdown_balance = starting_balance - drawdown_limit

    print(
        f"Daily drawdown limit set. Starting balance: {starting_balance}, Max drawdown balance: {max_drawdown_balance} based on tier {tier_size}")
    save_drawdown_data()


# Function to schedule the daily drawdown reset
def schedule_daily_reset(selected_account):
    now = datetime.now(pytz.timezone('America/New_York'))
    reset_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now >= reset_time:
        reset_time += timedelta(days=1)
    wait_time = (reset_time - now).total_seconds()
    threading.Timer(wait_time, perform_daily_reset, args=[selected_account]).start()


def perform_daily_reset(selected_account):
    reset_daily_drawdown(selected_account)
    schedule_daily_reset(selected_account)
