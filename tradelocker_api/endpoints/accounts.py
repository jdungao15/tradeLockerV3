import json
import os
import logging
from tradelocker_api.endpoints.auth import TradeLockerAuth
from tradelocker_api.api_client import ApiClient

logger = logging.getLogger(__name__)


class TradeLockerAccounts(ApiClient):
    """
    Client for TradeLocker accounts API with both synchronous and asynchronous methods
    """

    def __init__(self, auth: TradeLockerAuth):
        super().__init__(auth)
        self.selected_account_file = 'data/selected_account.json'

    # Synchronous methods (for backward compatibility)

    def get_accounts(self):
        """
        Fetch all accounts associated with the authenticated user.
        """
        try:
            # Cache account list for 5 minutes (300 seconds)
            return self.request('GET', 'auth/jwt/all-accounts', cache_ttl=300)
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")
            return None

    def get_account_state(self, account_id: int, acc_num):
        """
        Get account state by account ID.
        """
        try:
            headers = {"accNum": str(acc_num)}
            return self.request('GET', f'trade/accounts/{account_id}/state', headers=headers)
        except Exception as e:
            logger.error(f"Failed to fetch account state: {e}")
            return None

    def get_account_details(self, acc_num: int):
        """
        Get detailed information about the account using accNum.
        """
        try:
            headers = {"accNum": str(acc_num)}
            account_details = self.request('GET', 'trade/accounts', headers=headers)
            logger.info(f"Account details for accNum {acc_num}: {account_details}")
            return account_details
        except Exception as e:
            logger.error(f"Failed to fetch account details for accNum {acc_num}: {e}")
            return None

    def set_selected_account(self, account):
        """
        Set the selected account and store it in a JSON file for later use.
        """
        with open(self.selected_account_file, 'w') as file:
            json.dump(account, file)
        logger.debug(f"Selected account: {account['id']} saved to {self.selected_account_file}")

    def get_selected_account(self):
        """
        Retrieve the selected account from the JSON file.
        """
        if os.path.exists(self.selected_account_file):
            with open(self.selected_account_file, 'r') as file:
                account = json.load(file)
                return account
        else:
            logger.warning("No selected account found. Please select an account first.")
            return None

    def get_current_position(self, account_id: int, acc_num: int):
        """
        Retrieve the current open positions for the specified account.
        """
        try:
            headers = {"accNum": str(acc_num)}
            return self.request('GET', f'trade/accounts/{account_id}/positions', headers=headers)
        except Exception as e:
            logger.error(f"Failed to fetch open positions: {e}")
            return None

    # Asynchronous methods (for new code)

    async def get_accounts_async(self):
        """
        Fetch all accounts associated with the authenticated user - async version.
        """
        try:
            # Cache account list for 5 minutes (300 seconds)
            return await self.request_async('GET', 'auth/jwt/all-accounts', cache_ttl=300)
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")
            return None

    async def get_account_state_async(self, account_id: int, acc_num):
        """
        Get account state by account ID - async version.
        """
        try:
            headers = {"accNum": str(acc_num)}
            return await self.request_async('GET', f'trade/accounts/{account_id}/state', headers=headers)
        except Exception as e:
            logger.error(f"Failed to fetch account state: {e}")
            return None

    async def get_account_details_async(self, acc_num: int):
        """
        Get detailed information about the account using accNum - async version.
        """
        try:
            headers = {"accNum": str(acc_num)}
            account_details = await self.request_async('GET', 'trade/accounts', headers=headers)
            logger.info(f"Account details for accNum {acc_num}: {account_details}")
            return account_details
        except Exception as e:
            logger.error(f"Failed to fetch account details for accNum {acc_num}: {e}")
            return None

    async def get_current_position_async(self, account_id: int, acc_num: int):
        """
        Retrieve the current open positions for the specified account - async version.
        """
        try:
            headers = {"accNum": str(acc_num)}
            return await self.request_async('GET', f'trade/accounts/{account_id}/positions', headers=headers)
        except Exception as e:
            logger.error(f"Failed to fetch open positions: {e}")
            return None

    async def refresh_account_balance_async(self):
        """
        Refresh and return the current account balance - async version.
        """
        try:
            account = self.get_selected_account()
            if not account:
                logger.error("No selected account found")
                return None

            account_state = await self.get_account_state_async(account['id'], account['accNum'])
            if account_state and 'd' in account_state:
                # Update the stored account balance
                account['accountBalance'] = account_state['d'].get('balance', account['accountBalance'])
                self.set_selected_account(account)
                return account
            return account
        except Exception as e:
            logger.error("Failed to refresh account balance: {e}")
            return None
