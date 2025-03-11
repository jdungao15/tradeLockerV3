from datetime import datetime
from colorama import init, Fore, Style

def display_menu():
    """Display the main menu options"""
    print(f"\n{Fore.CYAN}===== MENU ====={Style.RESET_ALL}")
    print(f"{Fore.YELLOW}1.{Style.RESET_ALL} Start Trading Bot")
    print(f"{Fore.YELLOW}2.{Style.RESET_ALL} Exit")
    print(f"{Fore.CYAN}================{Style.RESET_ALL}\n")

    choice = input(f"{Fore.GREEN}Enter your choice (1-2): {Style.RESET_ALL}")
    return choice