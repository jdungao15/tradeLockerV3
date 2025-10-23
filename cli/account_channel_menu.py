"""
Account-Channel Configuration Menu Functions

CLI functions for managing multi-account channel routing
"""

from colorama import Fore, Style


def display_account_channel_menu():
    """Display account-channel configuration menu"""
    print(f"\n{Fore.CYAN}===== ACCOUNT-CHANNEL ROUTING ====={Style.RESET_ALL}")
    print(f"\n{Fore.YELLOW}1.{Style.RESET_ALL} View Current Configuration")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Configure Account Channels")
    print(f"{Fore.YELLOW}3.{Style.RESET_ALL} Enable/Disable Account Trading")
    print(f"{Fore.YELLOW}4.{Style.RESET_ALL} Add Channel to Account")
    print(f"{Fore.YELLOW}5.{Style.RESET_ALL} Remove Channel from Account")
    print(f"{Fore.YELLOW}6.{Style.RESET_ALL} Set Up New Account")
    print(f"{Fore.YELLOW}7.{Style.RESET_ALL} Export Configuration")
    print(f"{Fore.YELLOW}8.{Style.RESET_ALL} Back to Main Menu")
    print(f"{Fore.CYAN}===================================={Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-8): {Style.RESET_ALL}")
    return choice


def select_account_for_channel_config(account_manager):
    """
    Display accounts and let user select one for channel configuration

    Args:
        account_manager: AccountChannelManager instance

    Returns:
        tuple: (account_id, account_config) or (None, None) if cancelled
    """
    accounts = account_manager.get_all_accounts()

    if not accounts:
        print(f"{Fore.RED}No accounts configured yet{Style.RESET_ALL}")
        return None, None

    print(f"\n{Fore.CYAN}===== SELECT ACCOUNT ====={Style.RESET_ALL}\n")

    account_list = list(accounts.items())
    for idx, (key, config) in enumerate(account_list, 1):
        status = "✅ Enabled" if config.get('enabled', False) else "⏸️  Disabled"
        status_color = Fore.GREEN if config.get('enabled', False) else Fore.YELLOW

        channels = config.get('monitored_channels', [])
        channel_count = len(channels)

        print(f"{idx}. {config['name']} (#{config['accNum']})")
        print(f"    Status: {status_color}{status}{Style.RESET_ALL}")
        print(f"    Channels: {channel_count} configured {channels if channels else ''}")

    print(f"\n{Fore.YELLOW}0.{Style.RESET_ALL} Cancel")
    print(f"{Fore.CYAN}=========================={Style.RESET_ALL}\n")

    while True:
        try:
            choice = input(f"{Fore.GREEN}Select account (1-{len(account_list)}) or 0 to cancel: {Style.RESET_ALL}")
            choice_num = int(choice)

            if choice_num == 0:
                return None, None

            if 1 <= choice_num <= len(account_list):
                key, config = account_list[choice_num - 1]
                return config['account_id'], config
            else:
                print(f"{Fore.RED}Invalid selection{Style.RESET_ALL}")

        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")


def configure_account_channels(account_manager):
    """
    Configure which channels an account should trade

    Args:
        account_manager: AccountChannelManager instance
    """
    account_id, account_config = select_account_for_channel_config(account_manager)

    if not account_id:
        return

    print(f"\n{Fore.CYAN}Configuring channels for: {account_config['name']}{Style.RESET_ALL}")
    print(f"Current channels: {account_config.get('monitored_channels', [])}\n")

    # Input channel IDs
    print(f"{Fore.YELLOW}Enter channel IDs (comma-separated) or 'none' to clear:{Style.RESET_ALL}")
    print(f"Example: -1002153475473, -1002486712356")
    channel_input = input(f"{Fore.GREEN}Channels: {Style.RESET_ALL}").strip()

    if channel_input.lower() == 'none':
        channel_ids = []
    else:
        try:
            # Parse channel IDs
            channel_ids = [int(ch.strip()) for ch in channel_input.split(',') if ch.strip()]
        except ValueError:
            print(f"{Fore.RED}Invalid channel ID format{Style.RESET_ALL}")
            return

    # Update configuration
    if account_manager.set_account_channels(account_id, channel_ids):
        print(f"{Fore.GREEN}✅ Successfully updated channels for {account_config['name']}{Style.RESET_ALL}")
        print(f"New channels: {channel_ids}")
    else:
        print(f"{Fore.RED}❌ Failed to update channels{Style.RESET_ALL}")


def toggle_account_trading(account_manager):
    """
    Enable or disable trading for an account

    Args:
        account_manager: AccountChannelManager instance
    """
    account_id, account_config = select_account_for_channel_config(account_manager)

    if not account_id:
        return

    current_status = account_config.get('enabled', False)
    action = "Disable" if current_status else "Enable"

    confirm = input(f"\n{Fore.YELLOW}{action} trading for {account_config['name']}? (y/n): {Style.RESET_ALL}")

    if confirm.lower() == 'y':
        if current_status:
            account_manager.disable_account(account_id)
            print(f"{Fore.GREEN}✅ Trading disabled for {account_config['name']}{Style.RESET_ALL}")
        else:
            account_manager.enable_account(account_id)
            print(f"{Fore.GREEN}✅ Trading enabled for {account_config['name']}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}Cancelled{Style.RESET_ALL}")


def add_channel_to_account(account_manager):
    """
    Add a single channel to an account

    Args:
        account_manager: AccountChannelManager instance
    """
    account_id, account_config = select_account_for_channel_config(account_manager)

    if not account_id:
        return

    print(f"\n{Fore.CYAN}Adding channel to: {account_config['name']}{Style.RESET_ALL}")
    print(f"Current channels: {account_config.get('monitored_channels', [])}")

    channel_input = input(f"{Fore.GREEN}Enter channel ID to add: {Style.RESET_ALL}").strip()

    try:
        channel_id = int(channel_input)

        if account_manager.add_channel_to_account(account_id, channel_id):
            print(f"{Fore.GREEN}✅ Successfully added channel {channel_id}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}Channel may already exist or account not found{Style.RESET_ALL}")

    except ValueError:
        print(f"{Fore.RED}Invalid channel ID format{Style.RESET_ALL}")


def remove_channel_from_account(account_manager):
    """
    Remove a single channel from an account

    Args:
        account_manager: AccountChannelManager instance
    """
    account_id, account_config = select_account_for_channel_config(account_manager)

    if not account_id:
        return

    channels = account_config.get('monitored_channels', [])

    if not channels:
        print(f"{Fore.YELLOW}No channels configured for this account{Style.RESET_ALL}")
        return

    print(f"\n{Fore.CYAN}Removing channel from: {account_config['name']}{Style.RESET_ALL}")
    print(f"Current channels: {channels}")

    channel_input = input(f"{Fore.GREEN}Enter channel ID to remove: {Style.RESET_ALL}").strip()

    try:
        channel_id = int(channel_input)

        if account_manager.remove_channel_from_account(account_id, channel_id):
            print(f"{Fore.GREEN}✅ Successfully removed channel {channel_id}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}Channel not found in this account{Style.RESET_ALL}")

    except ValueError:
        print(f"{Fore.RED}Invalid channel ID format{Style.RESET_ALL}")


def setup_new_account(account_manager, accounts_data):
    """
    Set up a new account for multi-account trading

    Args:
        account_manager: AccountChannelManager instance
        accounts_data: Available accounts from TradeLocker
    """
    if not accounts_data or 'accounts' not in accounts_data:
        print(f"{Fore.RED}No account data available{Style.RESET_ALL}")
        return

    # Filter for only ACTIVE accounts
    all_accounts = accounts_data['accounts']
    accounts = [acc for acc in all_accounts if acc.get('status') == 'ACTIVE']

    if not accounts:
        print(f"{Fore.RED}No active accounts available{Style.RESET_ALL}")
        return

    print(f"\n{Fore.CYAN}===== SETUP NEW ACCOUNT ====={Style.RESET_ALL}\n")

    # Display available accounts
    for idx, account in enumerate(accounts, 1):
        account_num = account.get('accNum', 'Unknown')
        account_id = account.get('id', 'Unknown')
        balance = account.get('accountBalance', 0)

        # Convert balance to float if it's a string
        try:
            balance_float = float(balance)
        except (ValueError, TypeError):
            balance_float = 0.0

        # Check if already configured
        existing = account_manager.get_account_config(str(account_id))
        status = f" {Fore.YELLOW}[Already configured]{Style.RESET_ALL}" if existing else ""

        print(f"{idx}. Account #{account_num} (ID: {account_id})")
        print(f"    Balance: ${balance_float:,.2f}{status}")

    print(f"\n{Fore.YELLOW}0.{Style.RESET_ALL} Cancel")

    while True:
        try:
            choice = input(f"\n{Fore.GREEN}Select account (1-{len(accounts)}) or 0 to cancel: {Style.RESET_ALL}")
            choice_num = int(choice)

            if choice_num == 0:
                return

            if 1 <= choice_num <= len(accounts):
                selected_account = accounts[choice_num - 1]
                account_id = str(selected_account['id'])
                account_num = selected_account['accNum']

                # Get friendly name
                name_input = input(f"{Fore.GREEN}Enter a friendly name for this account: {Style.RESET_ALL}").strip()
                if not name_input:
                    name_input = f"Account {account_num}"

                # Get channel IDs
                print(f"\n{Fore.YELLOW}Enter Telegram channel IDs to monitor (comma-separated):{Style.RESET_ALL}")
                print(f"Example: -1002153475473, -1002486712356")
                print(f"Leave empty to configure later")
                channel_input = input(f"{Fore.GREEN}Channels: {Style.RESET_ALL}").strip()

                channel_ids = []
                if channel_input:
                    try:
                        channel_ids = [int(ch.strip()) for ch in channel_input.split(',') if ch.strip()]
                    except ValueError:
                        print(f"{Fore.RED}Invalid channel ID format, skipping channels{Style.RESET_ALL}")

                # Add account
                account_manager.add_account(
                    account_id=account_id,
                    account_num=account_num,
                    account_name=name_input,
                    monitored_channels=channel_ids,
                    enabled=True
                )

                print(f"\n{Fore.GREEN}✅ Successfully added {name_input}{Style.RESET_ALL}")
                print(f"Channels: {channel_ids if channel_ids else 'None (configure later)'}")
                return

            else:
                print(f"{Fore.RED}Invalid selection{Style.RESET_ALL}")

        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")
