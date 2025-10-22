import json
import os
import logging

logger = logging.getLogger(__name__)

# Simplified risk profile presets (only risk percentages)
RISK_PROFILES = {
    "conservative": {
        "FOREX": {
            "default": 0.005,  # 0.5% risk for standard forex pairs
            "reduced": 0.0025  # 0.25% risk for reduced risk signals
        },
        "CFD": {
            "default": 0.005,  # 0.5% risk for CFD instruments
            "reduced": 0.0025  # 0.25% risk for reduced risk signals
        },
        "XAUUSD": {
            "default": 0.005,  # 0.5% risk for Gold
            "reduced": 0.0025  # 0.25% risk for reduced risk signals
        },
        "drawdown": {
            "daily_percentage": 3.0  # 3% for conservative profile
        },
        "tp_selection": {
            "mode": "all",
            "custom_selection": [1, 2, 3, 4]
        }
    },
    "balanced": {
        "FOREX": {
            "default": 0.01,  # 1.0% risk for standard forex pairs
            "reduced": 0.005  # 0.5% risk for reduced risk signals
        },
        "CFD": {
            "default": 0.01,  # 1.0% risk for CFD instruments
            "reduced": 0.005  # 0.5% risk for reduced risk signals
        },
        "XAUUSD": {
            "default": 0.01,  # 1.0% risk for Gold
            "reduced": 0.005  # 0.5% risk for reduced risk signals
        },
        "drawdown": {
            "daily_percentage": 4.0  # 4% for balanced profile
        },
        "tp_selection": {
            "mode": "all",
            "custom_selection": [1, 2, 3, 4]
        }
    },
    "aggressive": {
        "FOREX": {
            "default": 0.015,  # 1.5% risk for standard forex pairs
            "reduced": 0.0075  # 0.75% risk for reduced risk signals
        },
        "CFD": {
            "default": 0.015,  # 1.5% risk for CFD instruments
            "reduced": 0.0075  # 0.75% risk for reduced risk signals
        },
        "XAUUSD": {
            "default": 0.015,  # 1.5% risk for Gold
            "reduced": 0.0075  # 0.75% risk for reduced risk signals
        },
        "drawdown": {
            "daily_percentage": 5.0  # 5% for aggressive profile
        },
        "tp_selection": {
            "mode": "all",
            "custom_selection": [1, 2, 3, 4]
        }
    }
}

# Default risk percentages (using balanced profile)
DEFAULT_RISK_CONFIG = RISK_PROFILES["balanced"].copy()

# Path to the config file
CONFIG_FILE = 'data/risk_settings.json'

# Global risk config structure:
# {
#     "global_default": {...},
#     "accounts": {
#         "account_number": {...}
#     }
# }
risk_config = {
    "global_default": DEFAULT_RISK_CONFIG.copy(),
    "accounts": {}
}


def load_risk_config():
    """Load risk configuration from file or create with defaults if not exists"""
    global risk_config

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)

                # Handle migration from old format
                if "global_default" not in loaded_config and "accounts" not in loaded_config:
                    # Old format - migrate to new format
                    logger.info("Migrating risk config from old format to new per-account format")
                    risk_config = {
                        "global_default": loaded_config,
                        "accounts": {}
                    }
                    save_risk_config()  # Save migrated format
                else:
                    risk_config = loaded_config

                logger.info(f"Loaded risk configuration from {CONFIG_FILE}")
        else:
            # Create the default config file if it doesn't exist
            save_risk_config()
            logger.info(f"Created default risk configuration file {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Error loading risk configuration: {e}")
        # Keep using the default configuration
        risk_config = {
            "global_default": DEFAULT_RISK_CONFIG.copy(),
            "accounts": {}
        }


def save_risk_config():
    """Save current risk configuration to file"""
    try:
        # Ensure directories exist
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

        with open(CONFIG_FILE, 'w') as f:
            json.dump(risk_config, f, indent=4)
        logger.info(f"Saved risk configuration to {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error saving risk configuration: {e}")
        return False


def _get_account_config(account_id=None):
    """
    Internal helper to get the appropriate config for an account

    Args:
        account_id: Account number/ID (if None, uses global_default)

    Returns:
        dict: The risk configuration for the account
    """
    if account_id is None:
        return risk_config["global_default"]

    # Convert account_id to string for consistent key lookups
    account_key = str(account_id)

    # Return account-specific config if it exists, otherwise global default
    if account_key in risk_config.get("accounts", {}):
        return risk_config["accounts"][account_key]
    else:
        return risk_config["global_default"]


def get_risk_percentage(instrument_type, reduced_risk=False, account_id=None):
    """
    Get the risk percentage for a specific instrument type

    Args:
        instrument_type: Type of instrument (FOREX, CFD, XAUUSD)
        reduced_risk: Whether to use reduced risk percentage
        account_id: Account number (if None, uses global_default)

    Returns:
        float: Risk percentage as a decimal (e.g., 0.01 for 1.0%)
    """
    config = _get_account_config(account_id)
    risk_type = "reduced" if reduced_risk else "default"

    # Check if instrument type exists in config, default to FOREX if not
    if instrument_type not in config:
        logger.warning(f"Unknown instrument type: {instrument_type}, using FOREX defaults")
        instrument_type = "FOREX"

    return config[instrument_type][risk_type]


def get_drawdown_percentage(account_id=None):
    """
    Get the daily drawdown percentage

    Args:
        account_id: Account number (if None, uses global_default)

    Returns:
        float: Drawdown percentage (e.g., 4.0 for 4%)
    """
    config = _get_account_config(account_id)

    if "drawdown" in config and "daily_percentage" in config["drawdown"]:
        return config["drawdown"]["daily_percentage"]
    else:
        # Default fallback
        return 4.0


def get_tp_selection(account_id=None):
    """
    Get the take profit selection configuration

    Args:
        account_id: Account number (if None, uses global_default)

    Returns:
        dict: TP selection configuration
    """
    config = _get_account_config(account_id)

    if "tp_selection" in config:
        return config["tp_selection"]

    # Default to using all take profits
    return {
        "mode": "all",
        "custom_selection": [1, 2, 3, 4]
    }


def detect_current_profile(account_id=None):
    """
    Detect which profile the current settings match, if any

    Args:
        account_id: Account number (if None, uses global_default)

    Returns:
        str: Profile name or 'custom'
    """
    config = _get_account_config(account_id)

    # Check for exact matches
    for profile_name, profile_settings in RISK_PROFILES.items():
        is_match = True

        # Check each instrument type's settings
        for instrument, settings in profile_settings.items():
            if instrument in ["drawdown", "tp_selection"]:
                continue  # Skip drawdown and tp_selection when matching profiles

            if instrument not in config:
                is_match = False
                break

            # For risk settings
            if config[instrument]["default"] != settings["default"] or \
                    config[instrument]["reduced"] != settings["reduced"]:
                is_match = False
                break

        if is_match:
            return profile_name

    return "custom"


def apply_risk_profile(profile_name, account_id=None):
    """
    Apply a predefined risk profile

    Args:
        profile_name: Name of the profile ('conservative', 'balanced', 'aggressive')
        account_id: Account number (if None, applies to global_default)

    Returns:
        bool: True if successful, False otherwise
    """
    if profile_name not in RISK_PROFILES:
        logger.error(f"Invalid risk profile: {profile_name}")
        return False

    # Deep copy the profile
    import copy
    profile_copy = copy.deepcopy(RISK_PROFILES[profile_name])

    if account_id is None:
        # Apply to global default
        risk_config["global_default"] = profile_copy
        logger.info(f"Applied {profile_name} risk profile to global defaults")
    else:
        # Apply to specific account
        account_key = str(account_id)
        if "accounts" not in risk_config:
            risk_config["accounts"] = {}
        risk_config["accounts"][account_key] = profile_copy
        logger.info(f"Applied {profile_name} risk profile to account {account_id}")

    # Save to file
    return save_risk_config()


def update_risk_percentage(instrument_type, percentage, is_reduced=False, account_id=None):
    """
    Update risk percentage for a specific instrument type

    Args:
        instrument_type: Type of instrument (FOREX, CFD, XAUUSD)
        percentage: Risk percentage as decimal (e.g., 0.01 for 1%)
        is_reduced: Whether to update reduced risk or normal risk
        account_id: Account number (if None, updates global_default)

    Returns:
        bool: Success status
    """
    if account_id is None:
        config = risk_config["global_default"]
        target_name = "global defaults"
    else:
        account_key = str(account_id)
        if "accounts" not in risk_config:
            risk_config["accounts"] = {}

        # Create account config if it doesn't exist (copy from global)
        if account_key not in risk_config["accounts"]:
            import copy
            risk_config["accounts"][account_key] = copy.deepcopy(risk_config["global_default"])

        config = risk_config["accounts"][account_key]
        target_name = f"account {account_id}"

    # Ensure instrument type exists
    if instrument_type not in config:
        config[instrument_type] = {
            "default": 0.01,
            "reduced": 0.005
        }

    # Update the appropriate risk type
    risk_type = "reduced" if is_reduced else "default"
    config[instrument_type][risk_type] = percentage

    # Save to file
    success = save_risk_config()

    logger.info(f"Updated {instrument_type} {risk_type} risk to {percentage * 100:.2f}% for {target_name}")
    return success


def update_drawdown_percentage(percentage, account_id=None):
    """
    Update the daily drawdown percentage

    Args:
        percentage: Drawdown percentage (e.g., 4.0 for 4%)
        account_id: Account number (if None, updates global_default)

    Returns:
        bool: Success status
    """
    if account_id is None:
        config = risk_config["global_default"]
        target_name = "global defaults"
    else:
        account_key = str(account_id)
        if "accounts" not in risk_config:
            risk_config["accounts"] = {}

        # Create account config if it doesn't exist
        if account_key not in risk_config["accounts"]:
            import copy
            risk_config["accounts"][account_key] = copy.deepcopy(risk_config["global_default"])

        config = risk_config["accounts"][account_key]
        target_name = f"account {account_id}"

    # Ensure drawdown section exists
    if "drawdown" not in config:
        config["drawdown"] = {}

    # Update drawdown percentage
    config["drawdown"]["daily_percentage"] = percentage

    logger.info(f"Updated daily drawdown to {percentage:.1f}% for {target_name}")

    # Save to file
    return save_risk_config()


def update_tp_selection(mode, custom_selection=None, account_id=None):
    """
    Update take profit selection settings

    Args:
        mode: Selection mode (e.g., 'all', 'first_only', etc.)
        custom_selection: List of TP indices when mode is 'custom'
        account_id: Account number (if None, updates global_default)

    Returns:
        bool: Success status
    """
    if account_id is None:
        config = risk_config["global_default"]
    else:
        account_key = str(account_id)
        if "accounts" not in risk_config:
            risk_config["accounts"] = {}

        # Create account config if it doesn't exist
        if account_key not in risk_config["accounts"]:
            import copy
            risk_config["accounts"][account_key] = copy.deepcopy(risk_config["global_default"])

        config = risk_config["accounts"][account_key]

    if "tp_selection" not in config:
        config["tp_selection"] = {}

    config["tp_selection"]["mode"] = mode

    if mode == "custom" and custom_selection:
        config["tp_selection"]["custom_selection"] = custom_selection
    elif mode == "custom" and not custom_selection:
        config["tp_selection"]["custom_selection"] = [1, 2, 3]

    return save_risk_config()


def get_all_account_ids():
    """
    Get list of all accounts with custom risk settings

    Returns:
        list: List of account IDs that have custom settings
    """
    return list(risk_config.get("accounts", {}).keys())


def delete_account_settings(account_id):
    """
    Delete custom risk settings for an account (reverts to global defaults)

    Args:
        account_id: Account number

    Returns:
        bool: Success status
    """
    account_key = str(account_id)

    if account_key in risk_config.get("accounts", {}):
        del risk_config["accounts"][account_key]
        logger.info(f"Deleted custom risk settings for account {account_id}")
        return save_risk_config()

    return True  # Already using global defaults


def copy_account_settings(from_account_id, to_account_id):
    """
    Copy risk settings from one account to another

    Args:
        from_account_id: Source account number (None for global_default)
        to_account_id: Target account number

    Returns:
        bool: Success status
    """
    import copy

    # Get source config
    source_config = _get_account_config(from_account_id)

    # Copy to target account
    to_account_key = str(to_account_id)
    if "accounts" not in risk_config:
        risk_config["accounts"] = {}

    risk_config["accounts"][to_account_key] = copy.deepcopy(source_config)

    logger.info(f"Copied risk settings from {from_account_id or 'global'} to account {to_account_id}")
    return save_risk_config()


def display_current_risk_settings(account_id=None):
    """
    Display the current risk settings in a formatted table

    Args:
        account_id: Account number (if None, shows global_default)
    """
    from colorama import Fore, Style

    config = _get_account_config(account_id)

    # Determine current profile
    current_profile = detect_current_profile(account_id)

    if current_profile == "conservative":
        profile_text = f"{Fore.BLUE}Conservative{Style.RESET_ALL}"
    elif current_profile == "balanced":
        profile_text = f"{Fore.GREEN}Balanced{Style.RESET_ALL}"
    elif current_profile == "aggressive":
        profile_text = f"{Fore.RED}Aggressive{Style.RESET_ALL}"
    else:
        profile_text = f"{Fore.YELLOW}Custom{Style.RESET_ALL}"

    account_label = f"Account {account_id}" if account_id else "Global Defaults"
    print(f"\n==== Risk Settings for {account_label} ({profile_text}) ====")
    print(f"{'Instrument Type':<15} {'Default Risk':<15} {'Reduced Risk':<15}")
    print("-" * 45)

    for instrument, settings in config.items():
        if instrument in ["drawdown", "tp_selection"]:
            continue  # Skip non-instrument settings

        default_risk = f"{settings['default'] * 100:.2f}%"
        reduced_risk = f"{settings['reduced'] * 100:.2f}%"
        print(f"{instrument:<15} {default_risk:<15} {reduced_risk:<15}")

    # Add drawdown info
    drawdown_pct = get_drawdown_percentage(account_id)
    print(f"\nDaily Drawdown: {drawdown_pct:.1f}%")

    # Add TP selection info if available
    tp_selection = get_tp_selection(account_id)
    print(f"TP Selection: {tp_selection['mode']}")

    print("=" * 45)


# Initialize by loading config at module import
load_risk_config()
