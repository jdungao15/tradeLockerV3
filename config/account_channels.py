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

    def add_account(self, account_id: str, account_num: str, account_name: str,
                    monitored_channels: List[int] = None, enabled: bool = True):
        """
        Add or update an account configuration

        Args:
            account_id: TradeLocker account ID
            account_num: Account number (for display)
            account_name: Friendly name for the account
            monitored_channels: List of Telegram channel IDs to monitor
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

    def set_account_channels(self, account_id: str, channel_ids: List[int]):
        """
        Set which channels an account should monitor for trading

        Args:
            account_id: TradeLocker account ID
            channel_ids: List of Telegram channel IDs
        """
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            self.config['accounts'][account_key]['monitored_channels'] = channel_ids
            self._save_config()
            logger.info(f"Updated channels for account {account_id}: {channel_ids}")
            return True
        else:
            logger.warning(f"Account {account_id} not found in configuration")
            return False

    def add_channel_to_account(self, account_id: str, channel_id: int):
        """Add a single channel to account's monitored channels"""
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            channels = self.config['accounts'][account_key]['monitored_channels']
            if channel_id not in channels:
                channels.append(channel_id)
                self._save_config()
                logger.info(f"Added channel {channel_id} to account {account_id}")
                return True
        return False

    def remove_channel_from_account(self, account_id: str, channel_id: int):
        """Remove a channel from account's monitored channels"""
        account_key = f"account_{account_id}"
        if account_key in self.config['accounts']:
            channels = self.config['accounts'][account_key]['monitored_channels']
            if channel_id in channels:
                channels.remove(channel_id)
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
        Check if an account should trade signals from a specific channel

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
        return channel_id in monitored_channels

    def get_accounts_for_channel(self, channel_id: int) -> List[Dict]:
        """
        Get all enabled accounts that should trade from a specific channel

        Args:
            channel_id: Telegram channel ID

        Returns:
            List of account configurations
        """
        trading_accounts = []
        for account_key, config in self.config['accounts'].items():
            if config.get('enabled', False):
                if channel_id in config.get('monitored_channels', []):
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
        all_channels = set(self.config.get('global_channels', []))

        for account_config in self.config['accounts'].values():
            all_channels.update(account_config.get('monitored_channels', []))

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
                # Display channel names if available, otherwise IDs
                if channel_names:
                    channel_display = [channel_names.get(ch_id, str(ch_id)) for ch_id in channels]
                    summary.append(f"     Channels: {', '.join(channel_display)}")
                else:
                    summary.append(f"     Channels: {channels}")
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
