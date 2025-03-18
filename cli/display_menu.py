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

    # Get current drawdown percentage
    drawdown_pct = risk_config.get_drawdown_percentage()

    # Get management settings
    mgmt_settings = risk_config.get_management_settings()
    auto_be = mgmt_settings.get("auto_breakeven", False)
    auto_close = mgmt_settings.get("auto_close_early", False)

    print(f"\n{Fore.CYAN}===== TRADING BOT MENU ====={Style.RESET_ALL}")

    # Display current profile information
    print(f"\n{Fore.CYAN}Current Risk Profile: {profile_display}{Style.RESET_ALL}")
    print(
        f"Risk Settings: Forex {Fore.YELLOW}{forex_risk:.1f}%{Style.RESET_ALL} | CFD {Fore.YELLOW}{cfd_risk:.1f}%{Style.RESET_ALL} | Gold {Fore.YELLOW}{gold_risk:.1f}%{Style.RESET_ALL} | Daily Drawdown {Fore.MAGENTA}{drawdown_pct:.1f}%{Style.RESET_ALL}")
    print(
        f"Auto-Breakeven: {Fore.GREEN if auto_be else Fore.RED}{'Enabled' if auto_be else 'Disabled'}{Style.RESET_ALL} | Auto-Close: {Fore.GREEN if auto_close else Fore.RED}{'Enabled' if auto_close else 'Disabled'}{Style.RESET_ALL}")

    # Menu options
    print(f"\n{Fore.YELLOW}1.{Style.RESET_ALL} Start Trading Bot")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Configure Risk Settings")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Exit")
    print(f"{Fore.CYAN}=============================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-3): {Style.RESET_ALL}")
    return choice


def display_risk_menu():
    """Display the risk management configuration menu with management toggles"""
    # Get current management settings
    mgmt_settings = risk_config.get_management_settings()
    auto_be = mgmt_settings.get("auto_breakeven", False)
    auto_close = mgmt_settings.get("auto_close_early", False)
    confirmation = mgmt_settings.get("confirmation_required", True)

    # Get current drawdown percentage
    drawdown_percentage = risk_config.get_drawdown_percentage()

    print(f"\n{Fore.CYAN}===== RISK MANAGEMENT CONFIGURATION ====={Style.RESET_ALL}")
    print(f"{Fore.YELLOW}1.{Style.RESET_ALL} View Current Risk Settings")

    # Risk profile options
    print(f"\n{Fore.CYAN}-- Risk Profiles --{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Apply {Fore.BLUE}Conservative{Style.RESET_ALL} Profile")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Apply {Fore.GREEN}Balanced{Style.RESET_ALL} Profile")
    print(f"{Fore.YELLOW}4.{Style.RESET_ALL} Apply {Fore.RED}Aggressive{Style.RESET_ALL} Profile")

    # Management settings options
    print(f"\n{Fore.CYAN}-- Signal Management --{Style.RESET_ALL}")
    print(
        f"{Fore.YELLOW}5.{Style.RESET_ALL} Auto-Breakeven: [{Fore.GREEN if auto_be else Fore.RED}{'ON' if auto_be else 'OFF'}{Style.RESET_ALL}]")
    print(
        f"{Fore.YELLOW}6.{Style.RESET_ALL} Auto-Close Early: [{Fore.GREEN if auto_close else Fore.RED}{'ON' if auto_close else 'OFF'}{Style.RESET_ALL}]")
    print(
        f"{Fore.YELLOW}7.{Style.RESET_ALL} Require Confirmation: [{Fore.GREEN if confirmation else Fore.RED}{'ON' if confirmation else 'OFF'}{Style.RESET_ALL}]")

    # Custom configuration options
    print(f"\n{Fore.CYAN}-- Custom Risk Percentages --{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}8.{Style.RESET_ALL} Configure Forex Risk")
    print(f"{Fore.YELLOW}9.{Style.RESET_ALL} Configure CFD Risk")
    print(f"{Fore.YELLOW}10.{Style.RESET_ALL} Configure XAUUSD (Gold) Risk")

    # NEW OPTION: Configure Daily Drawdown Percentage
    print(
        f"{Fore.YELLOW}11.{Style.RESET_ALL} Configure Daily Drawdown ({Fore.MAGENTA}{drawdown_percentage:.1f}%{Style.RESET_ALL})")

    # Moved these options down by one
    print(f"{Fore.YELLOW}12.{Style.RESET_ALL} Reset to Default Risk Settings")
    print(f"{Fore.YELLOW}13.{Style.RESET_ALL} Return to Main Menu")
    print(f"{Fore.CYAN}========================================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-13): {Style.RESET_ALL}")
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