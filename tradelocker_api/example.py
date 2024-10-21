from readchar import config
import json
from tradelocker_api.auth import TradeLockerAuth
from tradelocker_api.accounts import TradeLockerAccounts
from tradelocker_api.orders import TradeLockerOrders
from tradelocker_api.instruments import TradeLockerInstruments
from tradelocker_api.config import TradeLockerConfig
from tradelocker_api.quotes import TradeLockerQuotes
import pandas as pd

# Initialize the authentication
auth = TradeLockerAuth()

# Fetch and display account info
accounts_api = TradeLockerAccounts(auth)
accounts = accounts_api.get_accounts()


# Convert the accounts dictionary to a pandas DataFrame with only the required columns
accounts_df = pd.DataFrame(accounts['accounts'], columns=['id', 'currency', 'accNum', 'accountBalance'])

# Set pandas options to display all columns and rows without truncation
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)

# Print the accounts information in tabular format
print(accounts_df)

#get instrument by name
quotes_api = TradeLockerQuotes(auth)
# Get account ID
account_id = accounts['accounts'][0]['id']  # Example: Use the first account
account_num = accounts['accounts'][0]['accNum']
print(f"Account ID: {account_id}")
# Fetch and display available instruments
instruments_api = TradeLockerInstruments(auth)

instrument_name = instruments_api.get_instrument_by_name(account_id, account_num,"XAUUSD")

pos = accounts_api.get_current_position(879550, 50)
print(pos)


# Assuming `config` is an instance of TradeLockerConfig and `auth` is already set up

# print(accounts_api.get_account_state(869043,47))


# Define the file name to save the data


# Save the `config_data` to a JSON file
# if config_data:
#     try:
#         with open(config_file, 'w') as file:
#             json.dump(config_data, file, indent=4)
#         print(f"Configuration data saved to {config_file}.")
#     except IOError as e:
#         print(f"Failed to save configuration to {config_file}: {e}")
# else:
#     print("No configuration data to save.")
