#!/usr/bin/env python
"""
Comprehensive Telegram Channel ID Finder
Shows multiple ID formats to help identify the correct one for your bot.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, functions
from telethon.tl.types import Channel, Chat, User
from tabulate import tabulate
from colorama import init, Fore, Style

# Initialize colorama for colored output
init(autoreset=True)

# Load environment variables from .env file
load_dotenv()

# Get API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')

if not API_ID or not API_HASH:
    print(f"{Fore.RED}Error: API_ID and API_HASH must be set in your .env file{Style.RESET_ALL}")
    print("Create a .env file with:")
    print("API_ID=your_api_id")
    print("API_HASH=your_api_hash")
    sys.exit(1)


async def list_all_chat_formats():
    """Connect to Telegram and list all possible chat ID formats"""
    print(f"{Fore.CYAN}Connecting to Telegram...{Style.RESET_ALL}")

    # Create the client
    client = TelegramClient('./my_session', API_ID, API_HASH)

    try:
        # Connect and ensure authorized
        await client.connect()

        if not await client.is_user_authorized():
            print(f"{Fore.YELLOW}You are not authorized. Please login:{Style.RESET_ALL}")
            phone = input("Enter your phone number (with country code): ")
            await client.send_code_request(phone)
            code = input("Enter the code you received: ")
            await client.sign_in(phone, code)
            print(f"{Fore.GREEN}Successfully logged in!{Style.RESET_ALL}")

        print(f"{Fore.CYAN}Retrieving dialogs...{Style.RESET_ALL}")

        # Get all dialogs (chats, channels, etc.)
        dialogs = await client.get_dialogs()

        # Prepare data for display
        all_chats = []

        for dialog in dialogs:
            entity = dialog.entity

            # Skip users and bots
            if isinstance(entity, User):
                continue

            dialog_id = entity.id
            dialog_title = entity.title

            # Get username if available
            username = getattr(entity, 'username', None)
            username_str = f"@{username}" if username else "N/A"

            # Determine chat type
            if isinstance(entity, Channel):
                if entity.broadcast:
                    chat_type = "Channel"
                else:
                    chat_type = "Supergroup"
            elif isinstance(entity, Chat):
                chat_type = "Group"
            else:
                chat_type = "Unknown"

            # Generate multiple ID formats
            id_formats = {
                "Raw ID": dialog_id,
                "Negative ID": -dialog_id,
                "-100 Format": -1000000000000 - dialog_id,  # Example format
                "-1001 Format": -1001000000000 - dialog_id,  # Another common format
                "-1002 Format": -1002000000000 - dialog_id  # Yet another format
            }

            # For channels, also try to get real API ID
            real_api_id = None
            if isinstance(entity, Channel):
                try:
                    # Get full channel info
                    full_channel = await client(functions.channels.GetFullChannelRequest(
                        channel=entity
                    ))
                    # The actual ID used by the API may be available here
                    if hasattr(full_channel, 'full_chat'):
                        real_api_id = full_channel.full_chat.id
                        id_formats["Real API ID"] = real_api_id
                except Exception:
                    pass  # Ignore errors in getting full channel info

            # Add to our results
            all_chats.append([
                dialog_title,
                username_str,
                chat_type,
                id_formats.get("Raw ID"),
                id_formats.get("-100 Format"),
                id_formats.get("-1001 Format"),
                id_formats.get("-1002 Format")
            ])

        # Sort by name
        all_chats.sort(key=lambda x: x[0])

        # Display the results
        if all_chats:
            print(f"\n{Fore.GREEN}{Style.BRIGHT}ALL CHATS WITH MULTIPLE ID FORMATS:{Style.RESET_ALL}")
            print(tabulate(
                all_chats,
                headers=["Name", "Username", "Type", "Raw ID", "-100 Format", "-1001 Format", "-1002 Format"],
                tablefmt="pretty"
            ))

            # Show verification instructions
            print(f"\n{Fore.CYAN}How to verify the correct ID:{Style.RESET_ALL}")
            print("1. If you have a working channel ID in your bot, find the matching channel above.")
            print("2. Check which format matches your working ID.")
            print("3. Use that same format for any new channels you want to monitor.")

            # Show example for each channel
            print(f"\n{Fore.YELLOW}Examples for your bot:{Style.RESET_ALL}")
            for chat in all_chats:
                name = chat[0]
                chat_type = chat[2]
                id_minus100 = chat[4]
                id_minus1001 = chat[5]
                id_minus1002 = chat[6]

                print(f"\n{chat_type}: {Fore.GREEN}{name}{Style.RESET_ALL}")
                print(f"  Standard (-100) format: self.channel_ids.append({id_minus100})")
                print(f"  Extended (-1001) format: self.channel_ids.append({id_minus1001})")
                print(f"  Newer (-1002) format: self.channel_ids.append({id_minus1002})")
        else:
            print(f"{Fore.YELLOW}No chats found.{Style.RESET_ALL}")

    except Exception as e:
        print(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
    finally:
        # Disconnect
        await client.disconnect()


if __name__ == "__main__":
    # Run the async function
    asyncio.run(list_all_chat_formats())
