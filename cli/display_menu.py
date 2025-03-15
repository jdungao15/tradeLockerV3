from datetime import datetime
from colorama import init, Fore, Style


def display_menu():
    """Display the main menu options"""
    print(f"\n{Fore.CYAN}===== MENU ====={Style.RESET_ALL}")
    print(f"{Fore.YELLOW}1.{Style.RESET_ALL} Start Trading Bot")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Configure Risk Settings")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Exit")
    print(f"{Fore.CYAN}================{Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-3): {Style.RESET_ALL}")
    return choice


def display_risk_menu():
    """Display the risk management configuration menu"""
    print(f"\n{Fore.CYAN}===== RISK MANAGEMENT CONFIGURATION ====={Style.RESET_ALL}")
    print(f"{Fore.YELLOW}1.{Style.RESET_ALL} View Current Risk Settings")

    # Risk profile options
    print(f"\n{Fore.CYAN}-- Risk Profiles --{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Apply {Fore.BLUE}Conservative{Style.RESET_ALL} Profile")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Apply {Fore.GREEN}Balanced{Style.RESET_ALL} Profile")
    print(f"{Fore.YELLOW}4.{Style.RESET_ALL} Apply {Fore.RED}Aggressive{Style.RESET_ALL} Profile")

    # Custom configuration options
    print(f"\n{Fore.CYAN}-- Custom Configuration --{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}5.{Style.RESET_ALL} Configure Forex Risk")
    print(f"{Fore.YELLOW}6.{Style.RESET_ALL} Configure CFD Risk")
    print(f"{Fore.YELLOW}7.{Style.RESET_ALL} Configure XAUUSD (Gold) Risk")
    print(f"{Fore.YELLOW}8.{Style.RESET_ALL} Reset to Default Risk Settings")
    print(f"{Fore.YELLOW}9.{Style.RESET_ALL} Return to Main Menu")
    print(f"{Fore.CYAN}========================================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-9): {Style.RESET_ALL}")
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