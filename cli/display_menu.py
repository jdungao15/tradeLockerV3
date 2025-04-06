from datetime import datetime
from colorama import init, Fore, Style
import risk_config


def display_menu():
    """Display the main menu options with current risk profile settings"""
    # Get current risk profile
    current_profile = risk_config.detect_current_profile()

    # Format the profile name with color
    if current_profile == "conservative":
        profile_display = f"{Fore.BLUE}Conservative{Style.RESET_ALL}"
    elif current_profile == "balanced":
        profile_display = f"{Fore.GREEN}Balanced{Style.RESET_ALL}"
    elif current_profile == "aggressive":
        profile_display = f"{Fore.RED}Aggressive{Style.RESET_ALL}"
    else:
        profile_display = f"{Fore.YELLOW}Custom{Style.RESET_ALL}"

    # Get risk percentages for common instruments
    forex_risk = risk_config.get_risk_percentage("FOREX") * 100
    cfd_risk = risk_config.get_risk_percentage("CFD") * 100
    gold_risk = risk_config.get_risk_percentage("XAUUSD") * 100

    # Default drawdown percentage
    drawdown_pct = 4.0
    # Try to get from risk_config if the function exists
    if hasattr(risk_config, 'get_drawdown_percentage'):
        drawdown_pct = risk_config.get_drawdown_percentage()

    print(f"\n{Fore.CYAN}===== TRADING BOT MENU ====={Style.RESET_ALL}")

    # Display current profile information
    print(f"\n{Fore.CYAN}Current Risk Profile: {profile_display}{Style.RESET_ALL}")
    print(
        f"Risk Settings: Forex {Fore.YELLOW}{forex_risk:.1f}%{Style.RESET_ALL} | "
        f"CFD {Fore.YELLOW}{cfd_risk:.1f}%{Style.RESET_ALL} | "
        f"Gold {Fore.YELLOW}{gold_risk:.1f}%{Style.RESET_ALL} | "
        f"Daily Drawdown {Fore.MAGENTA}{drawdown_pct:.1f}%{Style.RESET_ALL}")

    # Menu options
    print(f"\n{Fore.YELLOW}1.{Style.RESET_ALL} Start Trading Bot")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Configure Risk Settings")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Exit")
    print(f"{Fore.CYAN}=============================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-3): {Style.RESET_ALL}")
    return choice


def display_risk_menu():
    """Display the risk management configuration menu"""
    # Default drawdown percentage
    drawdown_percentage = 4.0
    # Try to get from risk_config if the function exists
    if hasattr(risk_config, 'get_drawdown_percentage'):
        drawdown_percentage = risk_config.get_drawdown_percentage()

    print(f"\n{Fore.CYAN}===== RISK MANAGEMENT CONFIGURATION ====={Style.RESET_ALL}")
    print(f"{Fore.YELLOW}1.{Style.RESET_ALL} View Current Risk Settings")

    # Risk profile options
    print(f"\n{Fore.CYAN}-- Risk Profiles --{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Apply {Fore.BLUE}Conservative{Style.RESET_ALL} Profile (0.5%)")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Apply {Fore.GREEN}Balanced{Style.RESET_ALL} Profile (1.0%)")
    print(f"{Fore.YELLOW}4.{Style.RESET_ALL} Apply {Fore.RED}Aggressive{Style.RESET_ALL} Profile (1.5%)")

    # Custom configuration options
    print(f"\n{Fore.CYAN}-- Custom Risk Percentages --{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}5.{Style.RESET_ALL} Configure Forex Risk")
    print(f"{Fore.YELLOW}6.{Style.RESET_ALL} Configure CFD Risk")
    print(f"{Fore.YELLOW}7.{Style.RESET_ALL} Configure XAUUSD (Gold) Risk")

    # Drawdown option
    print(
        f"{Fore.YELLOW}8.{Style.RESET_ALL} Configure Daily Drawdown ({Fore.MAGENTA}{drawdown_percentage:.1f}%{Style.RESET_ALL})")

    # Management options
    print(f"\n{Fore.CYAN}-- Position Management --{Style.RESET_ALL}")

    # Get current management settings
    mgmt_settings = risk_config.get_management_settings()
    be_status = "Enabled" if mgmt_settings.get("auto_breakeven", True) else "Disabled"
    close_status = "Enabled" if mgmt_settings.get("auto_close_early", True) else "Disabled"
    confirm_status = "Yes" if mgmt_settings.get("confirmation_required", False) else "No"

    print(f"{Fore.YELLOW}9.{Style.RESET_ALL} Toggle Auto-Breakeven ({Fore.CYAN}{be_status}{Style.RESET_ALL})")
    print(f"{Fore.YELLOW}10.{Style.RESET_ALL} Toggle Auto-Close Early ({Fore.CYAN}{close_status}{Style.RESET_ALL})")
    print(
        f"{Fore.YELLOW}11.{Style.RESET_ALL} Toggle Confirmation Required ({Fore.CYAN}{confirm_status}{Style.RESET_ALL})")

    # Additional options
    print(f"{Fore.YELLOW}12.{Style.RESET_ALL} Configure Take Profit Selection")
    print(f"{Fore.YELLOW}13.{Style.RESET_ALL} Reset to Default Risk Settings")
    print(f"{Fore.YELLOW}14.{Style.RESET_ALL} Return to Main Menu")
    print(f"{Fore.CYAN}========================================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-14): {Style.RESET_ALL}")
    return choice


def get_risk_percentage_input(instrument_type, is_reduced=False):
    """
    Get risk percentage input from user

    Args:
        instrument_type: The type of instrument (for display)
        is_reduced: Whether asking for reduced risk

    Returns:
        float: Risk percentage as decimal (e.g., 0.015 for 1.5%) or None if invalid
    """
    risk_type = "reduced risk" if is_reduced else "normal risk"

    while True:
        try:
            risk_input = input(f"Enter {risk_type} percentage for {instrument_type} (e.g., 1.5 for 1.5%): ")
            risk_value = float(risk_input)

            # Validate range
            if 0 < risk_value <= 10:  # Allow up to 10% risk (though this is extremely high)
                return risk_value / 100  # Convert percentage to decimal
            else:
                print(f"{Fore.RED}Risk must be between 0% and 10%{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")

        retry = input("Try again? (y/n): ").lower()
        if retry != 'y':
            return None


def get_drawdown_percentage_input():
    """
    Get drawdown percentage input from user

    Returns:
        float: Drawdown percentage or None if invalid
    """
    # Get current drawdown percentage
    current_percentage = 4.0
    if hasattr(risk_config, 'get_drawdown_percentage'):
        current_percentage = risk_config.get_drawdown_percentage()

    print(f"\n{Fore.CYAN}Daily Drawdown Configuration{Style.RESET_ALL}")
    print(f"Current setting: {Fore.MAGENTA}{current_percentage:.1f}%{Style.RESET_ALL} of tier size")
    print(f"This setting determines how much of your account you can lose in a day.")
    print(f"PropFirm rules typically allow 4-5% maximum daily drawdown.")

    while True:
        try:
            percentage_input = input(f"Enter new daily drawdown percentage (1.0-10.0): ")
            percentage_value = float(percentage_input)

            # Validate range
            if 1.0 <= percentage_value <= 10.0:
                return percentage_value
            else:
                print(f"{Fore.RED}Drawdown percentage must be between 1% and 10%{Style.RESET_ALL}")

        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")

        retry = input("Try again? (y/n): ").lower()
        if retry != 'y':
            return None


def display_tp_selection_menu():
    """Display the take profit selection configuration menu"""
    # Default TP selection if the function isn't available
    current_tp_selection = {'mode': 'all', 'custom_selection': [1, 2, 3]}

    # Try to get from risk_config if the function exists
    if hasattr(risk_config, 'get_tp_selection'):
        current_tp_selection = risk_config.get_tp_selection()

    print(f"\n{Fore.CYAN}===== TAKE PROFIT SELECTION CONFIGURATION ====={Style.RESET_ALL}")
    print(f"Current selection method: {Fore.YELLOW}{current_tp_selection['mode']}{Style.RESET_ALL}")

    if current_tp_selection['mode'] == 'custom':
        tp_list = ', '.join([f'TP{i}' for i in current_tp_selection['custom_selection']])
        print(f"Custom selection: {Fore.GREEN}{tp_list}{Style.RESET_ALL}")

    # Print menu options
    print(f"\n{Fore.YELLOW}1.{Style.RESET_ALL} Use all take profits (default)")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Use only first take profit (TP1)")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Use first two take profits (TP1 & TP2)")
    print(f"{Fore.YELLOW}4.{Style.RESET_ALL} Use last two take profits")
    print(f"{Fore.YELLOW}5.{Style.RESET_ALL} Use odd-numbered take profits (TP1, TP3, etc.)")
    print(f"{Fore.YELLOW}6.{Style.RESET_ALL} Use even-numbered take profits (TP2, TP4, etc.)")
    print(f"{Fore.YELLOW}7.{Style.RESET_ALL} Configure custom TP selection")
    print(f"{Fore.YELLOW}8.{Style.RESET_ALL} Return to Risk Menu")

    choice = input(f"{Fore.GREEN}Enter your choice (1-8): {Style.RESET_ALL}")
    return choice