# order_handler.py

from tradelocker_api.orders import TradeLockerOrders

def place_order(orders_client, selected_account, instrument_data, parsed_signal, position_sizes, colored_time):
    """
    Places orders for the given instrument and parsed signal.
    """
    try:
        for position_size, take_profit in zip(position_sizes, parsed_signal['take_profits']):
            order_params = {
                'account_id': selected_account['id'],
                'acc_num': selected_account['accNum'],
                'instrument': instrument_data,
                'quantity': position_size,
                'side': parsed_signal['order_type'],
                'order_type': 'limit',
                'price': parsed_signal['entry_point'],
                'stop_loss': parsed_signal['stop_loss'],
                'take_profit': take_profit,
            }

            print("Placing order...")
            order_response = orders_client.create_order(**order_params)
            if order_response:
                print(f"{colored_time}: Order placed successfully: {order_response}")
            else:
                print(f"{colored_time}: Failed to place order.")

    except Exception as e:
        print(f"{colored_time}: Error placing order: {e}")
