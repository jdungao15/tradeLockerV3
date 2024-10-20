from tabulate import tabulate


def pretty_print_accounts(accounts_data):
    # Extract the relevant fields from the nested dictionary
    accounts = accounts_data.get('accounts', [])

    # Prepare the headers for the table
    headers = ["Account ID", "Account Number", "Account Balance", "Currency"]

    # Prepare the rows for the table
    table_data = [
        [account['id'], account['accNum'], account['accountBalance'], account['currency']]
        for account in accounts
    ]

    # Use tabulate to print the table
    print(tabulate(table_data, headers=headers, tablefmt="pretty"))