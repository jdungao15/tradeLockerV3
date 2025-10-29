#!/usr/bin/env python3
"""
Update Channel Names in account_channels.json

This script fetches the actual channel names from Telegram and updates
the account_channels.json file with the real channel names instead of placeholders.
"""

import asyncio
import json
import os
import sys
import logging
from telethon import TelegramClient
from dotenv import load_dotenv

# Add parent directory to path to import config modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.account_channels import AccountChannelManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


async def get_channel_name(client, channel_id):
    """
    Fetch the channel name from Telegram

    Args:
        client: Telegram client
        channel_id: Channel ID to fetch

    Returns:
        str: Channel name or None if not accessible
    """
    try:
        entity = await client.get_entity(channel_id)
        if hasattr(entity, 'title'):
            return entity.title
        return f"Channel {channel_id}"
    except Exception as e:
        logger.warning(f"Could not fetch name for channel {channel_id}: {e}")
        return None


async def update_channel_names():
    """Main function to update channel names in account_channels.json"""

    # Load environment variables
    load_dotenv()
    api_id = os.getenv('API_ID')
    api_hash = os.getenv('API_HASH')

    if not api_id or not api_hash:
        logger.error("Missing API_ID or API_HASH in .env file")
        return False

    # Load account channel manager
    manager = AccountChannelManager()

    logger.info("=" * 70)
    logger.info("UPDATING CHANNEL NAMES IN ACCOUNT_CHANNELS.JSON")
    logger.info("=" * 70)
    logger.info("")

    # Initialize Telegram client
    client = None
    try:
        client = TelegramClient('./my_session', int(api_id), api_hash)

        # Suppress Telethon debug messages
        logging.getLogger('telethon').setLevel(logging.WARNING)

        await client.connect()

        if not await client.is_user_authorized():
            logger.error("Telegram client not authorized. Please run the main bot first to authenticate.")
            return False

        logger.info("✅ Connected to Telegram")
        logger.info("")

        # Track statistics
        total_channels = 0
        updated_channels = 0
        failed_channels = 0

        # Get all accounts
        accounts = manager.get_all_accounts()

        # Process each account
        for account_key, account_config in accounts.items():
            account_name = account_config.get('name', 'Unknown')
            account_num = account_config.get('accNum', '?')
            monitored_channels = account_config.get('monitored_channels', [])

            logger.info(f"Processing account: {account_name} (#{account_num})")

            if not monitored_channels:
                logger.info("  No channels configured")
                logger.info("")
                continue

            # Update channel names
            updated_channels_list = []

            for ch_entry in monitored_channels:
                total_channels += 1

                # Handle both old format (int) and new format ([int, str])
                if isinstance(ch_entry, list) and len(ch_entry) >= 1:
                    channel_id = int(ch_entry[0])
                    current_name = ch_entry[1] if len(ch_entry) >= 2 else None
                else:
                    channel_id = int(ch_entry)
                    current_name = None

                # Fetch the real channel name
                logger.info(f"  Fetching name for channel {channel_id}...")
                real_name = await get_channel_name(client, channel_id)

                if real_name:
                    updated_channels_list.append([channel_id, real_name])
                    logger.info(f"    ✅ Updated: {real_name}")
                    updated_channels += 1
                else:
                    # Keep the old name or use a generic placeholder
                    fallback_name = current_name if current_name else f"Channel {channel_id}"
                    updated_channels_list.append([channel_id, fallback_name])
                    logger.info(f"    ⚠️  Could not fetch name, using: {fallback_name}")
                    failed_channels += 1

            # Update the account's monitored channels
            account_config['monitored_channels'] = updated_channels_list
            logger.info("")

        # Save the updated configuration
        manager._save_config()

        logger.info("=" * 70)
        logger.info("SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total channels processed: {total_channels}")
        logger.info(f"Successfully updated: {updated_channels}")
        logger.info(f"Failed to fetch: {failed_channels}")
        logger.info("=" * 70)
        logger.info("")
        logger.info("✅ Configuration updated successfully!")
        logger.info("")

        return True

    except Exception as e:
        logger.error(f"Error updating channel names: {e}", exc_info=True)
        return False

    finally:
        if client:
            await client.disconnect()


def main():
    """Entry point for the script"""
    try:
        success = asyncio.run(update_channel_names())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
