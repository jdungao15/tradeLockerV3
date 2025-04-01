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
        }
    }
}

# Default risk percentages (using balanced profile)
DEFAULT_RISK_CONFIG = RISK_PROFILES["balanced"]

# Path to the config file
CONFIG_FILE = 'risk_settings.json'

# Global risk config that will be loaded from file or defaults
risk_config = DEFAULT_RISK_CONFIG.copy()


def load_risk_config():
    """Load risk configuration from file or create with defaults if not exists"""
    global risk_config

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                risk_config = loaded_config
                logger.info(f"Loaded risk configuration from {CONFIG_FILE}")
        else:
            # Create the default config file if it doesn't exist
            save_risk_config()
            logger.info(f"Created default risk configuration file {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Error loading risk configuration: {e}")
        # Keep using the default configuration
        risk_config = DEFAULT_RISK_CONFIG.copy()


def save_risk_config():
    """Save current risk configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(risk_config, f, indent=4)
        logger.info(f"Saved risk configuration to {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error saving risk configuration: {e}")
        return False


def get_risk_percentage(instrument_type, reduced_risk=False):
    """
    Get the risk percentage for a specific instrument type

    Args:
        instrument_type: Type of instrument (FOREX, CFD, XAUUSD)
        reduced_risk: Whether to use reduced risk percentage

    Returns:
        float: Risk percentage as a decimal (e.g., 0.01 for 1.0%)
    """
    risk_type = "reduced" if reduced_risk else "default"

    # Check if instrument type exists in config, default to FOREX if not
    if instrument_type not in risk_config:
        logger.warning(f"Unknown instrument type: {instrument_type}, using FOREX defaults")
        instrument_type = "FOREX"

    return risk_config[instrument_type][risk_type]


def detect_current_profile():
    """Detect which profile the current settings match, if any"""
    # Check for exact matches
    for profile_name, profile_settings in RISK_PROFILES.items():
        is_match = True

        # Check each instrument type's settings
        for instrument, settings in profile_settings.items():
            if instrument == "drawdown":
                continue  # Skip drawdown when matching profiles

            if instrument not in risk_config:
                is_match = False
                break

            # For risk settings
            if risk_config[instrument]["default"] != settings["default"] or \
                    risk_config[instrument]["reduced"] != settings["reduced"]:
                is_match = False
                break

        if is_match:
            return profile_name

    return "custom"


def apply_risk_profile(profile_name):
    """
    Apply a predefined risk profile

    Args:
        profile_name: Name of the profile to apply ('conservative', 'balanced', 'aggressive')

    Returns:
        bool: True if successful, False otherwise
    """
    global risk_config

    if profile_name not in RISK_PROFILES:
        logger.error(f"Invalid risk profile: {profile_name}")
        return False

    # Apply the selected profile
    risk_config = RISK_PROFILES[profile_name].copy()

    # Save to file
    success = save_risk_config()

    if success:
        logger.info(f"Applied {profile_name} risk profile")

    return success


def get_drawdown_percentage():
    """
    Get the current daily drawdown percentage

    Returns:
        float: Drawdown percentage (e.g., 4.0 for 4%)
    """
    if "drawdown" in risk_config and "daily_percentage" in risk_config["drawdown"]:
        return risk_config["drawdown"]["daily_percentage"]
    else:
        # Default based on current profile
        current_profile = detect_current_profile()
        if current_profile == "conservative":
            return 3.0
        elif current_profile == "aggressive":
            return 3.0
        else:  # balanced or custom
            return 3.0


def update_drawdown_percentage(percentage):
    """
    Update the daily drawdown percentage

    Args:
        percentage: Drawdown percentage (e.g., 4.0 for 4%)

    Returns:
        bool: Success status
    """
    global risk_config

    # Ensure drawdown section exists
    if "drawdown" not in risk_config:
        risk_config["drawdown"] = {}

    # Update drawdown percentage
    risk_config["drawdown"]["daily_percentage"] = percentage

    # Save to file
    return save_risk_config()


def update_risk_percentage(instrument_type, percentage, is_reduced=False):
    """
    Update risk percentage for a specific instrument type

    Args:
        instrument_type: Type of instrument (FOREX, CFD, XAUUSD)
        percentage: Risk percentage as decimal (e.g., 0.01 for 1%)
        is_reduced: Whether to update reduced risk or normal risk

    Returns:
        bool: Success status
    """
    global risk_config

    # Ensure instrument type exists
    if instrument_type not in risk_config:
        risk_config[instrument_type] = {
            "default": 0.01,
            "reduced": 0.005
        }

    # Update the appropriate risk type
    risk_type = "reduced" if is_reduced else "default"
    risk_config[instrument_type][risk_type] = percentage

    # Save to file
    success = save_risk_config()

    logger.info(f"Updated {instrument_type} {risk_type} risk to {percentage * 100:.2f}%")
    return success

def get_tp_selection():
    """
    Get the current take profit selection configuration

    Returns:
        dict: TP selection configuration
    """
    if "tp_selection" in risk_config:
        return risk_config["tp_selection"]

    # Default to using all take profits
    return {
        "mode": "all",
        "custom_selection": [1, 2, 3, 4]
    }


def update_tp_selection(mode, custom_selection=None):
    """
    Update take profit selection settings

    Args:
        mode: Selection mode (e.g., 'all', 'first_only', etc.)
        custom_selection: List of TP indices when mode is 'custom'

    Returns:
        bool: Success status
    """
    global risk_config

    if "tp_selection" not in risk_config:
        risk_config["tp_selection"] = {}

    risk_config["tp_selection"]["mode"] = mode

    if mode == "custom" and custom_selection:
        risk_config["tp_selection"]["custom_selection"] = custom_selection
    elif mode == "custom" and not custom_selection:
        risk_config["tp_selection"]["custom_selection"] = [1, 2, 3]

    return save_risk_config()


def display_current_risk_settings():
    """Display the current risk settings in a formatted table"""
    from colorama import Fore, Style

    # Determine current profile
    current_profile = detect_current_profile()

    if current_profile == "conservative":
        profile_text = f"{Fore.BLUE}Conservative{Style.RESET_ALL}"
    elif current_profile == "balanced":
        profile_text = f"{Fore.GREEN}Balanced{Style.RESET_ALL}"
    elif current_profile == "aggressive":
        profile_text = f"{Fore.RED}Aggressive{Style.RESET_ALL}"
    else:
        profile_text = f"{Fore.YELLOW}Custom{Style.RESET_ALL}"

    print(f"\n==== Current Risk Settings ({profile_text}) ====")
    print(f"{'Instrument Type':<15} {'Default Risk':<15} {'Reduced Risk':<15}")
    print("-" * 45)

    for instrument, settings in risk_config.items():
        if instrument in ["drawdown", "tp_selection"]:
            continue  # Skip non-instrument settings

        default_risk = f"{settings['default'] * 100:.2f}%"
        reduced_risk = f"{settings['reduced'] * 100:.2f}%"
        print(f"{instrument:<15} {default_risk:<15} {reduced_risk:<15}")

    # Add drawdown info
    drawdown_pct = get_drawdown_percentage()
    print(f"\nDaily Drawdown: {drawdown_pct:.1f}%")

    # Add TP selection info if available
    tp_selection = get_tp_selection()
    print(f"TP Selection: {tp_selection['mode']}")

    print("=" * 45)



# Initialize by loading config at module import
load_risk_config()