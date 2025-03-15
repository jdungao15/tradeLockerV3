import json
import os
import logging

logger = logging.getLogger(__name__)

# Risk profile presets
RISK_PROFILES = {
    "conservative": {
        "FOREX": {
            "default": 0.01,  # 1.0% risk for standard forex pairs
            "reduced": 0.005  # 0.5% risk for reduced risk signals
        },
        "CFD": {
            "default": 0.0075,  # 0.75% risk for CFD instruments
            "reduced": 0.004  # 0.4% risk for reduced risk signals
        },
        "XAUUSD": {
            "default": 0.01,  # 1.0% risk for Gold
            "reduced": 0.005  # 0.5% risk for reduced risk signals
        }
    },
    "balanced": {
        "FOREX": {
            "default": 0.015,  # 1.5% risk for standard forex pairs
            "reduced": 0.0075  # 0.75% risk for reduced risk signals
        },
        "CFD": {
            "default": 0.01,  # 1.0% risk for CFD instruments
            "reduced": 0.005  # 0.5% risk for reduced risk signals
        },
        "XAUUSD": {
            "default": 0.015,  # 1.5% risk for Gold
            "reduced": 0.0075  # 0.75% risk for reduced risk signals
        }
    },
    "aggressive": {
        "FOREX": {
            "default": 0.02,  # 2.0% risk for standard forex pairs
            "reduced": 0.01  # 1.0% risk for reduced risk signals
        },
        "CFD": {
            "default": 0.015,  # 1.5% risk for CFD instruments
            "reduced": 0.0075  # 0.75% risk for reduced risk signals
        },
        "XAUUSD": {
            "default": 0.02,  # 2.0% risk for Gold
            "reduced": 0.01  # 1.0% risk for reduced risk signals
        }
    }
}

# Default risk percentages by instrument type (using balanced profile)
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
        float: Risk percentage as a decimal (e.g., 0.015 for 1.5%)
    """
    risk_type = "reduced" if reduced_risk else "default"

    # Check if instrument type exists in config, default to FOREX if not
    if instrument_type not in risk_config:
        logger.warning(f"Unknown instrument type: {instrument_type}, using FOREX defaults")
        instrument_type = "FOREX"

    return risk_config[instrument_type][risk_type]


def update_risk_percentage(instrument_type, risk_value, is_reduced=False):
    """
    Update the risk percentage for a specific instrument type

    Args:
        instrument_type: Type of instrument (FOREX, CFD, XAUUSD)
        risk_value: Risk percentage as a decimal (e.g., 0.015 for 1.5%)
        is_reduced: Whether to update the reduced risk percentage

    Returns:
        bool: True if update was successful, False otherwise
    """
    risk_type = "reduced" if is_reduced else "default"

    # Validate inputs
    if instrument_type not in risk_config:
        logger.error(f"Invalid instrument type: {instrument_type}")
        return False

    if not 0 < risk_value <= 0.1:  # Limit risk to between 0% and 10%
        logger.error(f"Invalid risk value: {risk_value}. Must be between 0 and 0.1")
        return False

    # Update the configuration
    risk_config[instrument_type][risk_type] = risk_value

    # Save changes to file
    return save_risk_config()


def display_current_risk_settings():
    """Display the current risk settings in a formatted table"""
    # Determine current profile
    current_profile = detect_current_profile()

    print(f"\n==== Current Risk Settings {current_profile_text(current_profile)} ====")
    print(f"{'Instrument Type':<15} {'Default Risk':<15} {'Reduced Risk':<15}")
    print("-" * 45)

    for instrument, settings in risk_config.items():
        default_risk = f"{settings['default'] * 100:.2f}%"
        reduced_risk = f"{settings['reduced'] * 100:.2f}%"
        print(f"{instrument:<15} {default_risk:<15} {reduced_risk:<15}")

    print("=" * 45)


def current_profile_text(profile):
    """Format the current profile text with color"""
    from colorama import Fore, Style

    if profile == "conservative":
        return f"({Fore.BLUE}Conservative{Style.RESET_ALL})"
    elif profile == "balanced":
        return f"({Fore.GREEN}Balanced{Style.RESET_ALL})"
    elif profile == "aggressive":
        return f"({Fore.RED}Aggressive{Style.RESET_ALL})"
    else:
        return f"({Fore.YELLOW}Custom{Style.RESET_ALL})"


def detect_current_profile():
    """Detect which profile the current settings match, if any"""
    for profile_name, profile_settings in RISK_PROFILES.items():
        if risk_config == profile_settings:
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


# Initialize by loading config at module import
load_risk_config()