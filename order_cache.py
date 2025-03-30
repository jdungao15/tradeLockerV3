import json
import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class OrderCache:
    """
    Cache to store order IDs mapped to telegram message IDs with persistence
    """

    def __init__(self, cache_file='order_cache.json'):
        self.cache_file = cache_file
        self.orders_map = {}
        self.load_cache()

    def load_cache(self):
        """Load cache from file"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    self.orders_map = json.load(f)
                logger.info(f"Loaded order cache with {len(self.orders_map)} entries")
            else:
                logger.info("No order cache file found. Creating new cache.")
                self.save_cache()  # Create empty file
        except Exception as e:
            logger.error(f"Error loading order cache: {e}")
            self.orders_map = {}  # Reset to empty if error

    def save_cache(self):
        """Save cache to file"""
        try:
            # Create backup of existing file if it exists
            if os.path.exists(self.cache_file):
                backup_file = f"{self.cache_file}.bak"
                try:
                    with open(self.cache_file, 'r') as src:
                        with open(backup_file, 'w') as dst:
                            dst.write(src.read())
                except Exception as e:
                    logger.warning(f"Could not create backup of cache file: {e}")

            with open(self.cache_file, 'w') as f:
                json.dump(self.orders_map, f, indent=2)
            logger.info(f"Saved order cache with {len(self.orders_map)} entries")
            return True
        except Exception as e:
            logger.error(f"Error saving order cache: {e}")
            return False

    def store_orders(self, message_id, order_ids, take_profits, instrument=None):
        """
        Store order IDs with message ID and take profits

        Args:
            message_id: Telegram message ID
            order_ids: List of order IDs
            take_profits: List of take profit levels
            instrument: Optional instrument name
        """
        if not message_id or not order_ids:
            return False

        self.orders_map[str(message_id)] = {
            'orders': order_ids,
            'take_profits': take_profits,
            'instrument': instrument,
            'timestamp': datetime.now().isoformat(),
            'order_status': {}  # Will hold status updates for each order
        }

        return self.save_cache()

    def get_orders(self, message_id):
        """
        Get orders associated with a message ID

        Args:
            message_id: Telegram message ID

        Returns:
            dict: Order data or None if not found
        """
        return self.orders_map.get(str(message_id))

    def update_order_status(self, message_id, order_id, status):
        """
        Update order status in cache

        Args:
            message_id: Telegram message ID
            order_id: Order ID to update
            status: New status (e.g., 'active', 'filled', 'cancelled')
        """
        if str(message_id) in self.orders_map:
            if 'order_status' not in self.orders_map[str(message_id)]:
                self.orders_map[str(message_id)]['order_status'] = {}

            self.orders_map[str(message_id)]['order_status'][str(order_id)] = {
                'status': status,
                'updated': datetime.now().isoformat()
            }

            return self.save_cache()
        return False

    def cleanup_old_entries(self, days=7):
        """
        Remove entries older than specified days

        Args:
            days: Number of days to keep entries
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff_date.isoformat()

        keys_to_remove = []

        for message_id, data in self.orders_map.items():
            timestamp = data.get('timestamp')
            if timestamp and timestamp < cutoff_str:
                keys_to_remove.append(message_id)

        if keys_to_remove:
            for key in keys_to_remove:
                del self.orders_map[key]

            logger.info(f"Removed {len(keys_to_remove)} old entries from order cache")
            self.save_cache()

    def get_active_orders(self):
        """
        Get all orders that haven't been marked as closed or cancelled

        Returns:
            dict: Message ID -> list of active order IDs
        """
        active_orders = {}

        for message_id, data in self.orders_map.items():
            order_ids = data.get('orders', [])
            order_status = data.get('order_status', {})

            # Filter out orders that are already closed or cancelled
            active_ids = []
            for order_id in order_ids:
                status_info = order_status.get(str(order_id), {})
                status = status_info.get('status')

                if status not in ['closed', 'cancelled']:
                    active_ids.append(order_id)

            if active_ids:
                active_orders[message_id] = active_ids

        return active_orders

    def get_order_details(self, order_id):
        """
        Find message ID and details for a specific order ID

        Args:
            order_id: Order ID to find

        Returns:
            tuple: (message_id, order_details) or (None, None) if not found
        """
        order_id_str = str(order_id)

        for message_id, data in self.orders_map.items():
            order_ids = [str(oid) for oid in data.get('orders', [])]

            if order_id_str in order_ids:
                # Get position in orders list to match with take profits
                try:
                    position = order_ids.index(order_id_str)
                    take_profits = data.get('take_profits', [])
                    take_profit = take_profits[position] if position < len(take_profits) else None

                    # Build details
                    details = {
                        'take_profit': take_profit,
                        'instrument': data.get('instrument'),
                        'timestamp': data.get('timestamp'),
                        'status': data.get('order_status', {}).get(order_id_str, {}).get('status')
                    }

                    return message_id, details
                except Exception as e:
                    logger.error(f"Error getting order details: {e}")

        return None, None