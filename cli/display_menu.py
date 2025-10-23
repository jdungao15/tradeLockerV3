from colorama import Fore, Style
import config.risk_config as risk_config


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
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Configure Account-Channel Routing")
    print(f"{Fore.YELLOW}4.{Style.RESET_ALL} Exit")
    print(f"{Fore.CYAN}=============================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-4): {Style.RESET_ALL}")
    return choice


def display_risk_menu():
    """Display the initial risk management menu with account selection"""
    print(f"\n{Fore.CYAN}===== RISK MANAGEMENT CONFIGURATION ====={Style.RESET_ALL}")

    # Get list of accounts with custom settings
    custom_accounts = risk_config.get_all_account_ids()

    print(f"\n{Fore.CYAN}-- Configure Risk Settings --{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}1.{Style.RESET_ALL} Configure Global Default Settings")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Configure Per-Account Settings")

    if custom_accounts:
        print(f"\n{Fore.CYAN}-- Accounts with Custom Settings --{Style.RESET_ALL}")
        for idx, account_id in enumerate(custom_accounts, 1):
            print(f"  • Account {account_id}")

    print(f"\n{Fore.YELLOW}3.{Style.RESET_ALL} Return to Main Menu")
    print(f"{Fore.CYAN}========================================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-3): {Style.RESET_ALL}")
    return choice


def display_account_risk_menu(account_id=None):
    """
    Display risk configuration menu for a specific account or global defaults

    Args:
        account_id: Account number (None for global defaults)
    """
    # Default drawdown percentage
    drawdown_percentage = risk_config.get_drawdown_percentage(account_id)

    account_label = f"Account {account_id}" if account_id else "Global Defaults"
    print(f"\n{Fore.CYAN}===== RISK CONFIGURATION: {account_label} ====={Style.RESET_ALL}")
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
    print(f"{Fore.YELLOW}8.{Style.RESET_ALL} Configure Daily Drawdown "
          f"({Fore.MAGENTA}{drawdown_percentage:.1f}%{Style.RESET_ALL})")

    # Additional options
    print(f"{Fore.YELLOW}9.{Style.RESET_ALL} Reset to Default Risk Settings")
    print(f"{Fore.YELLOW}10.{Style.RESET_ALL} Configure Take Profit Selection")

    # Account-specific options
    if account_id is not None:
        print(f"\n{Fore.CYAN}-- Account Management --{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}12.{Style.RESET_ALL} Delete Custom Settings (Revert to Global)")

    print(f"\n{Fore.YELLOW}11.{Style.RESET_ALL} Return to Previous Menu")
    print(f"{Fore.CYAN}================================================{Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice: {Style.RESET_ALL}")
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
    print("This setting determines how much of your account you can lose in a day.")
    print("PropFirm rules typically allow 4-5% maximum daily drawdown.")

    while True:
        try:
            percentage_input = input("Enter new daily drawdown percentage (1.0-10.0): ")
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


def select_account_for_configuration(accounts_data):
    """
    Prompt user to select an account for risk configuration

    Args:
        accounts_data: Dictionary containing account information from TradeLocker API

    Returns:
        str: Account number or None if cancelled
    """
    print(f"\n{Fore.CYAN}===== SELECT ACCOUNT FOR CONFIGURATION ====={Style.RESET_ALL}")

    if not accounts_data or 'accounts' not in accounts_data:
        print(f"{Fore.RED}No account data available{Style.RESET_ALL}")
        return None

    accounts = accounts_data['accounts']

    # Display available accounts
    print(f"\n{Fore.CYAN}Available Accounts:{Style.RESET_ALL}\n")
    for idx, account in enumerate(accounts, 1):
        account_num = account.get('accNum', 'Unknown')
        balance = account.get('accountBalance', 0)
        status = account.get('status', 'Unknown')

        # Check if this account has custom risk settings
        has_custom = account_num in risk_config.get_all_account_ids()
        custom_indicator = f" {Fore.YELLOW}[Custom]{Style.RESET_ALL}" if has_custom else ""

        # Color code by status
        status_color = Fore.GREEN if status == 'ACTIVE' else Fore.RED

        print(f"{idx}. Account: {Fore.CYAN}{account_num}{Style.RESET_ALL} | "
              f"Balance: ${balance:,.2f} | "
              f"Status: {status_color}{status}{Style.RESET_ALL}{custom_indicator}")

    print(f"\n{Fore.YELLOW}0.{Style.RESET_ALL} Cancel")
    print(f"{Fore.CYAN}==========================================={Style.RESET_ALL}\n")

    while True:
        try:
            choice = input(f"{Fore.GREEN}Select account (1-{len(accounts)}) or 0 to cancel: {Style.RESET_ALL}")
            choice_num = int(choice)

            if choice_num == 0:
                return None

            if 1 <= choice_num <= len(accounts):
                selected_account = accounts[choice_num - 1]
                return selected_account.get('accNum')
            else:
                print(f"{Fore.RED}Invalid selection. Please choose 1-{len(accounts)} or 0 to cancel{Style.RESET_ALL}")

        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
