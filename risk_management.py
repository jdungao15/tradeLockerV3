import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()


# Exchange rate
def get_exchange_rate(base: str, quote: str) -> float:
    try:
        host = "https://api.frankfurter.app"
        amount = 1
        url = f"{host}/latest?amount={amount}&from={base}&to={quote}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data['rates'][quote]
    except Exception as error:
        print(f"Error fetching exchange rate: {error}")
        raise


# Calculate stop loss in pips
def calculate_stop_loss_pips(stop_loss: float, entry_point: float, instrument: dict) -> float:
    if instrument['name'].endswith("JPY"):
        return abs(stop_loss - entry_point) / 0.01
    elif instrument['type'] == "FOREX":
        return abs(stop_loss - entry_point) / 0.0001
    return abs(stop_loss - entry_point)


# Calculate pip value for an instrument
def calculate_pip_value(instrument: dict) -> float:
    if instrument["type"] == "FOREX":
        base_currency = instrument["name"][:3]
        quote_currency = instrument["name"][3:]

        exchange_rate = get_exchange_rate(base_currency, quote_currency)
        pip_value = 0.01 / exchange_rate if instrument["name"].endswith("JPY") else 0.0001 / exchange_rate

    elif instrument["type"] == "EQUITY_CFD":
        pip_values = {
            "NDX100": 20,
            "DJI30": 5,
            "XAUUSD": 100
        }

        if instrument["name"] not in pip_values:
            raise ValueError(f"Invalid index type: {instrument['name']}")

        pip_value = pip_values[instrument["name"]]

    else:
        raise ValueError(f"Unsupported instrument type: {instrument['type']}")

    return pip_value


# Determine the risk percentage based on account tiers
def determine_risk_percentage(account_balance: float, instrument: dict) -> float:
    # Define account tiers and corresponding risk percentages for FOREX and XAUUSD
    tiers = {
        5000: 0.02,  # Risk 2% for 5k accounts
        10000: 0.015,  # Risk 1.5% for 10k accounts
        25000: 0.015,  # Risk 1% for 25k accounts
        50000: 0.015,  # Risk 1% for 50k accounts
        100000: 0.015  # Risk 1% for 100k accounts
    }

    # Special handling for XAUUSD, which should follow the same risk as FOREX
    if instrument["name"] == "XAUUSD":
        # Determine the closest tier based on account balance for XAUUSD
        closest_tier = max(tier for tier in tiers if account_balance >= tier)
        risk_percentage = tiers[closest_tier]
        print(
            f"Account balance: {account_balance}, Closest tier: {closest_tier}, Risk percentage for XAUUSD: {risk_percentage * 100}%")
        return risk_percentage

    # If the instrument type is EQUITY_CFD but not XAUUSD, set a fixed risk percentage of 0.5%
    if instrument["type"] == "EQUITY_CFD":
        return 1.5  # 0.5%

    # Determine the closest tier based on account balance for other instruments
    closest_tier = max(tier for tier in tiers if account_balance >= tier)
    risk_percentage = tiers[closest_tier]
    print(
        f"Account balance: {account_balance}, Closest tier: {closest_tier}, Risk percentage: {risk_percentage * 100}%")
    return risk_percentage


# Main function to calculate position size
def calculate_position_size(
    instrument: dict,
    entry_point: float,
    stop_loss: float,
    take_profits: list,
    account: dict
) -> tuple:
    account_balance = float(account['accountBalance'])

    # Determine the risk percentage based on account tiers and instrument type
    risk_percentage = determine_risk_percentage(account_balance, instrument)

    # Calculate the pip value for the instrument
    pip_value = calculate_pip_value(instrument)

    # Calculate the total amount you are willing to risk
    risk_amount = account_balance * risk_percentage
    stop_loss_pips = calculate_stop_loss_pips(stop_loss, entry_point, instrument)

    # Convert risk amount to base currency if necessary
    converted_risk_amount = risk_amount
    if instrument['type'] == "FOREX":
        base_currency = instrument['name'][:3]

        # MAJOR PAIRS
        if base_currency != "USD" and "USD" in instrument['name']:
            conversion_rate = get_exchange_rate("USD", base_currency)
            converted_risk_amount = risk_amount * conversion_rate
        elif "USD" not in instrument['name']:
            # MINOR PAIRS
            conversion_rate_to_usd = get_exchange_rate(base_currency, "USD")
            converted_risk_amount = risk_amount / conversion_rate_to_usd

    # Calculate position size for indices
    if instrument['type'] == "EQUITY_CFD":
        total_pos_in_lots = converted_risk_amount / (stop_loss_pips * pip_value)
        position_per_tp = total_pos_in_lots / len(take_profits)
        position_sizes = [round(position_per_tp, 2) for _ in take_profits]
    else:
        # Calculate total position size for forex
        total_pos_in_units = converted_risk_amount / (stop_loss_pips * pip_value)
        total_pos_in_lots = total_pos_in_units / 100_000
        position_size_per_tp = round(total_pos_in_lots / len(take_profits), 2 if instrument['name'].endswith("JPY") else 1)
        position_sizes = [position_size_per_tp for _ in take_profits]

    print(f"Calculated position sizes: {position_sizes}, Risk amount: {risk_amount}")
    return position_sizes, round(risk_amount)
