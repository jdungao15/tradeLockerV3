"""
Account-Channel Configuration Manager

Manages which trading accounts should monitor and trade which Telegram channels.
Each account can be configured to trade signals from specific channels.
"""

import json
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AccountChannelManager:
    """Manages account-to-channel mappings for multi-account trading"""

    def __init__(self, config_file='data/account_channels.json'):
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Load account-channel configuration from file"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading account-channel config: {e}")
                return {'accounts': {}, 'global_channels': []}
        else:
            # Create default empty config
            default_config = {
                'accounts': {},
                'global_channels': [],  # Channels visible to all (monitoring only)
                'last_updated': None
            }
            self._save_config(default_config)
            return default_config

    def _save_config(self, config=None):
        """Save configuration to file"""
        if config is None:
            config = self.config

        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            logger.debug("Account-channel configuration saved")
        except Exception as e:
            logger.error(f"Error saving account-channel config: {e}")

    def _normalize_channel_id(self, channel_entry):
        """
        Normalize channel entry to just the channel ID.
        Handles both old format (int) and new format ([int, str]).

        Args:
            channel_entry: Either an int (channel ID) or [int, str] (channel ID + name)

        Returns:
            int: The channel ID
        """
        if isinstance(channel_entry, list) and len(channel_entry) >= 1:
            return int(channel_entry[0])
        return int(channel_entry)

    def _get_channel_id_variants(self, channel_id: int) -> List[int]:
        """
        Generate all possible Telegram channel ID format variants.

        Telegram represents the same channel in multiple ID formats:
        - Positive form (e.g., 1234567890)
        - Simple negative (e.g., -1234567890)
        - With -100 prefix (older format)
        - With -1001 prefix (intermediate format)
        - With -1002 prefix (newer format)

        This method generates all possible variants to handle cases where
        Telegram reports the channel ID in a different format than what's stored.

        Args:
            channel_id: The channel ID to generate variants for

        Returns:
            List of all possible channel ID variants
        """
        variants = set()

        # Get the base ID (absolute value)
        base_id = abs(channel_id)

        # Add positive and negative forms
        variants.add(base_id)
        variants.add(-base_id)

        # Handle -100, -1001, -1002 prefixed IDs
        # First, check if this is already a prefixed ID and extract the base
        if channel_id < -1000000000000:  # Has a -100x prefix
            # Extract the base from prefixed format
            if str(channel_id).startswith('-1002'):
                extracted_base = abs(channel_id) - 1002000000000
            elif str(channel_id).startswith('-1001'):
                extracted_base = abs(channel_id) - 1001000000000
            elif str(channel_id).startswith('-100'):
                extracted_base = abs(channel_id) - 100000000000
            else:
                extracted_base = base_id

            # Add all variant forms using the extracted base
            variants.add(extracted_base)
            variants.add(-extracted_base)
            variants.add(-100000000000 - extracted_base)
            variants.add(-1001000000000 - extracted_base)
            variants.add(-1002000000000 - extracted_base)
        else:
            # Generate prefixed variants from the base ID
            variants.add(-100000000000 - base_id)
            variants.add(-1001000000000 - base_id)
            variants.add(-1002000000000 - base_id)

        # Remove 0 if it somehow got added
        variants.discard(0)

        # Convert to list and sort for consistent ordering
        return sorted(list(variants))


    def _get_channel_name(self, channel_entry):
        """
        Get channel name from entry if available.

        Args:
            channel_entry: Either an int (channel ID) or [int, str] (channel ID + name)

        Returns:
            str: Channel name or None if not available
        """
        if isinstance(channel_entry, list) and len(channel_entry) >= 2:
            return channel_entry[1]
        return None

    def add_account(self, account_id: str, account_num: str, account_name: str,
                    monitored_channels: List = None, enabled: bool = True):
        """
        Add or update an account configuration

        Args:
            account_id: TradeLocker account ID
            account_num: Account number (for display)
            account_name: Friendly name for the account
            monitored_channels: List of channel entries (can be int or [int, str])
            enabled: Whether this account should trade
        """
        if monitored_channels is None:
            monitored_channels = []

        account_key = f"account_{account_id}"
        self.config['accounts'][account_key] = {
            'account_id': account_id,
            'accNum': account_num,
            'name': account_name,
            'monitored_channels': monitored_channels,
            'enabled': enabled
        }
        self._save_config()
        logger.info(f"Added/updated account configuration: {account_name}")

    def remove_account(self, account_id: str):
        """Remove an account from configuration"""
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            del self.config['accounts'][account_key]
            self._save_config()
            logger.info(f"Removed account configuration: {account_id}")
            return True
        return False

    def set_account_channels(self, account_id: str, channel_entries: List):
        """
        Set which channels an account should monitor for trading

        Args:
            account_id: TradeLocker account ID
            channel_entries: List of channel entries (can be int or [int, str])
        """
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            self.config['accounts'][account_key]['monitored_channels'] = channel_entries
            self._save_config()
            logger.info(f"Updated channels for account {account_id}: {channel_entries}")
            return True
        else:
            logger.warning(f"Account {account_id} not found in configuration")
            return False

    def add_channel_to_account(self, account_id: str, channel_id: int, channel_name: str = None):
        """
        Add a single channel to account's monitored channels

        Args:
            account_id: TradeLocker account ID
            channel_id: Telegram channel ID
            channel_name: Optional channel name for display
        """
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            channels = self.config['accounts'][account_key]['monitored_channels']
            # Normalize existing channels to check for duplicates
            normalized_ids = [self._normalize_channel_id(ch) for ch in channels]

            if channel_id not in normalized_ids:
                # Add in new format with name if provided
                if channel_name:
                    channels.append([channel_id, channel_name])
                else:
                    channels.append([channel_id, f"Channel {channel_id}"])
                self._save_config()
                logger.info(f"Added channel {channel_id} to account {account_id}")
                return True
        return False

    def remove_channel_from_account(self, account_id: str, channel_id: int):
        """Remove a channel from account's monitored channels"""
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            channels = self.config['accounts'][account_key]['monitored_channels']
            # Find and remove the channel (handles both old and new format)
            for i, ch_entry in enumerate(channels):
                if self._normalize_channel_id(ch_entry) == channel_id:
                    channels.pop(i)
                    self._save_config()
                    logger.info(f"Removed channel {channel_id} from account {account_id}")
                    return True
        return False

    def enable_account(self, account_id: str):
        """Enable trading for an account"""
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            self.config['accounts'][account_key]['enabled'] = True
            self._save_config()
            return True
        return False

    def disable_account(self, account_id: str):
        """Disable trading for an account"""
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            self.config['accounts'][account_key]['enabled'] = False
            self._save_config()
            return True
        return False

    def get_account_config(self, account_id: str) -> Optional[Dict]:
        """Get configuration for a specific account"""
        account_key = f"account_{account_id}"
        return self.config['accounts'].get(account_key)

    def get_all_accounts(self) -> Dict:
        """Get all account configurations"""
        return self.config['accounts']

    def get_enabled_accounts(self) -> Dict:
        """Get only enabled accounts"""
        return {
            key: config for key, config in self.config['accounts'].items()
            if config.get('enabled', False)
        }

    def should_account_trade_channel(self, account_id: str, channel_id: int) -> bool:
        """
        Check if an account should trade signals from a specific channel.

        Uses channel ID variant matching to handle cases where Telegram reports
        the channel ID in a different format than what's stored in configuration.

        Args:
            account_id: TradeLocker account ID
            channel_id: Telegram channel ID

        Returns:
            bool: True if account should trade this channel
        """
        account_key = f"account_{account_id}"
        account_config = self.config['accounts'].get(account_key)

        if not account_config:
            return False

        if not account_config.get('enabled', False):
            return False

        monitored_channels = account_config.get('monitored_channels', [])
        # Normalize channel entries to just IDs
        normalized_channels = [self._normalize_channel_id(ch) for ch in monitored_channels]

        # Generate all possible variants of the incoming channel ID
        channel_variants = self._get_channel_id_variants(channel_id)

        # Check if any variant matches any configured channel
        return any(variant in normalized_channels for variant in channel_variants)

    def get_accounts_for_channel(self, channel_id: int) -> List[Dict]:
        """
        Get all enabled accounts that should trade from a specific channel.

        Uses channel ID variant matching to handle cases where Telegram reports
        the channel ID in a different format than what's stored in configuration.

        Args:
            channel_id: Telegram channel ID

        Returns:
            List of account configurations
        """
        trading_accounts = []

        # Generate all possible variants of the incoming channel ID
        channel_variants = self._get_channel_id_variants(channel_id)

        for account_key, config in self.config['accounts'].items():
            if config.get('enabled', False):
                monitored_channels = config.get('monitored_channels', [])
                # Normalize channel entries to just IDs
                normalized_channels = [self._normalize_channel_id(ch) for ch in monitored_channels]

                # Check if any variant matches any configured channel
                if any(variant in normalized_channels for variant in channel_variants):
                    trading_accounts.append(config)

        return trading_accounts

    def set_global_channels(self, channel_ids: List[int]):
        """
        Set global monitoring channels (visible to all, but don't trigger trades)

        Args:
            channel_ids: List of Telegram channel IDs
        """
        self.config['global_channels'] = channel_ids
        self._save_config()
        logger.info(f"Updated global monitoring channels: {channel_ids}")

    def get_all_monitored_channels(self) -> List[int]:
        """
        Get ALL channels that should be monitored (global + all account channels)

        Returns:
            List of unique channel IDs
        """
        all_channels = set()

        # Add global channels (normalize if needed)
        for ch in self.config.get('global_channels', []):
            all_channels.add(self._normalize_channel_id(ch))

        # Add account-specific channels (normalize if needed)
        for account_config in self.config['accounts'].values():
            for ch in account_config.get('monitored_channels', []):
                all_channels.add(self._normalize_channel_id(ch))

        return list(all_channels)

    def export_config(self) -> str:
        """Export configuration as formatted JSON string"""
        return json.dumps(self.config, indent=2)

    def import_config(self, config_json: str) -> bool:
        """
        Import configuration from JSON string

        Args:
            config_json: JSON string with configuration

        Returns:
            bool: Success status
        """
        try:
            new_config = json.loads(config_json)
            self.config = new_config
            self._save_config()
            logger.info("Configuration imported successfully")
            return True
        except Exception as e:
            logger.error(f"Error importing configuration: {e}")
            return False

    def validate_accounts_against_api(self, api_accounts_data: Dict) -> Dict:
        """
        Validate configured accounts against current API account data.
        Automatically removes accounts that no longer exist or are not ACTIVE.

        Args:
            api_accounts_data: Response from TradeLocker API get_accounts() call
                              Expected format: {'accounts': [{'id': ..., 'status': ...}, ...]}

        Returns:
            Dict with keys:
                'removed': List of removed account IDs
                'removed_accounts': List of removed account configs (for logging)
                'valid': List of valid account IDs still in config
        """
        if not api_accounts_data or 'accounts' not in api_accounts_data:
            logger.warning("No API account data provided for validation")
            return {'removed': [], 'removed_accounts': [], 'valid': []}

        # Build set of valid (ACTIVE) account IDs from API
        valid_account_ids = set()
        for acc in api_accounts_data.get('accounts', []):
            if acc.get('status') == 'ACTIVE':
                valid_account_ids.add(str(acc.get('id')))

        # Check configured accounts
        removed_account_ids = []
        removed_account_configs = []
        valid_configured_ids = []

        accounts_to_remove = []
        for account_key, config in self.config['accounts'].items():
            account_id = config.get('account_id')

            if account_id not in valid_account_ids:
                # Account is either deleted or not ACTIVE anymore
                accounts_to_remove.append(account_key)
                removed_account_ids.append(account_id)
                removed_account_configs.append({
                    'id': account_id,
                    'name': config.get('name'),
                    'accNum': config.get('accNum')
                })
                logger.warning(
                    f"Removing invalid account from config: "
                    f"{config.get('name')} (#{config.get('accNum')}, ID: {account_id})"
                )
            else:
                valid_configured_ids.append(account_id)

        # Remove invalid accounts
        for account_key in accounts_to_remove:
            del self.config['accounts'][account_key]

        # Save if any accounts were removed
        if accounts_to_remove:
            self._save_config()
            logger.info(f"Removed {len(accounts_to_remove)} invalid account(s) from configuration")

        return {
            'removed': removed_account_ids,
            'removed_accounts': removed_account_configs,
            'valid': valid_configured_ids
        }

    def get_summary(self, channel_names: dict = None) -> str:
        """
        Get a summary of the current configuration

        Args:
            channel_names: Optional dict mapping channel_id -> channel_name
        """
        summary = []
        summary.append(f"\n{'='*70}")
        summary.append("ACCOUNT-CHANNEL CONFIGURATION")
        summary.append(f"{'='*70}")

        enabled_accounts = self.get_enabled_accounts()
        disabled_accounts = {k: v for k, v in self.config['accounts'].items() if not v.get('enabled', False)}

        summary.append(f"\nEnabled Trading Accounts: {len(enabled_accounts)}")
        for account_key, config in enabled_accounts.items():
            summary.append(f"\n  ✅ {config['name']} (#{config['accNum']})")
            channels = config.get('monitored_channels', [])
            if channels:
                # Display channel names from stored data or from channel_names dict
                channel_display = []
                for ch_entry in channels:
                    ch_id = self._normalize_channel_id(ch_entry)
                    ch_name = self._get_channel_name(ch_entry)

                    # Use stored name if available, otherwise fallback to channel_names dict
                    if ch_name:
                        channel_display.append(f"{ch_name} ({ch_id})")
                    elif channel_names and ch_id in channel_names:
                        channel_display.append(f"{channel_names[ch_id]} ({ch_id})")
                    else:
                        channel_display.append(str(ch_id))

                summary.append(f"     Channels: {', '.join(channel_display)}")
            else:
                summary.append(f"     Channels: None (won't trade)")

        if disabled_accounts:
            summary.append(f"\nDisabled Accounts: {len(disabled_accounts)}")
            for account_key, config in disabled_accounts.items():
                summary.append(f"  ⏸️  {config['name']} (#{config['accNum']})")

        global_channels = self.config.get('global_channels', [])
        if global_channels:
            if channel_names:
                global_channel_display = [channel_names.get(ch_id, str(ch_id)) for ch_id in global_channels]
                summary.append(f"\nGlobal Monitoring Channels: {', '.join(global_channel_display)}")
            else:
                summary.append(f"\nGlobal Monitoring Channels: {global_channels}")
            summary.append("  (All accounts can see these, but won't trade them)")

        all_channels = self.get_all_monitored_channels()
        summary.append(f"\nTotal Monitored Channels: {len(all_channels)}")

        summary.append(f"{'='*70}\n")
        return '\n'.join(summary)
