import requests
from tradelocker_api.auth import TradeLockerAuth
import json
import os



class TradeLockerAccounts:
    def __init__(self, auth: TradeLockerAuth):
        self.auth = auth
        self.base_url = auth.base_url
        self.selected_account_file = 'selected_account.json'  # File to store the selected account

    def get_accounts(self):
        """
        Fetch all accounts associated with the authenticated user.
        """
        url = f"{self.base_url}/auth/jwt/all-accounts"
        headers = {"Authorization": f"Bearer {self.auth.get_access_token()}"}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch accounts: {e}")
            return None

    def get_account_state(self, account_id: int, acc_num):
        """
        Get account state by account ID.
        """
        url = f"{self.base_url}/trade/accounts/{account_id}/state"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num)
                   }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch account state: {e}")
            return None

    def get_account_details(self, acc_num: int):
        """
        Get detailed information about the account using accNum.
        """
        url = f"{self.base_url}/trade/accounts"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num)  # Required header as shown in the API documentation
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            account_details = response.json()
            print(f"Account details for accNum {acc_num}: {account_details}")
            return account_details
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch account details for accNum {acc_num}: {e}")
            return None

    def set_selected_account(self, account):
        """
        Set the selected account and store it in a JSON file for later use.
        """
        with open(self.selected_account_file, 'w') as file:
            json.dump(account, file)
        print(f"Selected account: {account['id']} saved to {self.selected_account_file}")

    def get_selected_account(self):
        """
        Retrieve the selected account from the JSON file.
        """
        if os.path.exists(self.selected_account_file):
            with open(self.selected_account_file, 'r') as file:
                account = json.load(file)
                return account
        else:
            print(f"No selected account found. Please select an account first.")
            return None

    def get_current_position(self, account_id: int, acc_num: int):
        """
        Retrieve the current open positions for the specified account.
        """
        url = f"{self.base_url}/trade/accounts/{account_id}/positions"
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "accNum": str(acc_num)  # Required by the API
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            positions = response.json()
            print(f"Open positions for account ID {account_id}: {positions}")
            return positions
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch open positions: {e}")
            return None
