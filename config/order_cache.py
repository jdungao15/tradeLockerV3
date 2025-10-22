import json
import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Global static memory cache that persists across instances
GLOBAL_ORDER_CACHE = {}


class OrderCache:
    """
    Simplified cache with memory-first approach that persists across restarts
    and handles order deletion after successful cancellation
    """

    def __init__(self, cache_file='data/order_cache.json'):
        self.cache_file = cache_file
        # Use the global cache for in-memory storage
        global GLOBAL_ORDER_CACHE

        # Load from file only if global cache is empty
        if not GLOBAL_ORDER_CACHE:
            self.load_cache()
        # Silent - cache loaded

    def load_cache(self):
        """Load cache from file into global memory"""
        global GLOBAL_ORDER_CACHE

        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    loaded_data = json.load(f)

                # Update global cache
                GLOBAL_ORDER_CACHE.update(loaded_data)
                # Silent - cache loaded
            else:
                # No cache file - save empty cache to create the file
                self.save_cache()
        except Exception as e:
            logger.error(f"Error loading order cache: {e}")
            # Don't reset global cache if it has data

    def save_cache(self):
        """Save global memory cache to file for persistence"""
        global GLOBAL_ORDER_CACHE

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

            # Write global cache to file
            with open(self.cache_file, 'w') as f:
                json.dump(GLOBAL_ORDER_CACHE, f, indent=2)

            # Silent - cache saved
            return True
        except Exception as e:
            logger.error(f"Error saving order cache: {e}")
            return False

    def store_orders(self, message_id, order_ids, take_profits, instrument=None, entry_price=None):
        """
        Store order IDs with message ID, take profits, and entry price in global memory first

        Args:
            message_id: Telegram message ID (will be converted to string)
            order_ids: List of order IDs
            take_profits: List of take profit levels
            instrument: Optional instrument name
            entry_price: Entry price for breakeven functionality
        """
        global GLOBAL_ORDER_CACHE

        if not message_id or not order_ids:
            logger.warning(f"Cannot store orders: missing message_id ({message_id}) or order_ids ({order_ids})")
            return False

        # Ensure message_id is a string for consistency
        str_message_id = str(message_id)

        # Ensure order_ids are strings
        str_order_ids = [str(order_id) for order_id in order_ids]

        # Store in global cache first
        GLOBAL_ORDER_CACHE[str_message_id] = {
            'orders': str_order_ids,
            'take_profits': take_profits,
            'instrument': instrument,
            'entry_price': entry_price,  # Store entry price
            'timestamp': datetime.now().isoformat()
        }

        # Debug logging (only in log files)
        logger.debug(f"Stored orders for message_id: '{str_message_id}' with {len(order_ids)} orders")
        logger.debug(f"Verification: message_id {str_message_id} in memory cache: {str_message_id in GLOBAL_ORDER_CACHE}")
        logger.debug(f"Cache updated, current keys: {list(GLOBAL_ORDER_CACHE.keys())}")

        # Save to file as backup
        return self.save_cache()

    def get_orders(self, message_id):
        """
        Get orders associated with a message ID directly from global memory
        """
        global GLOBAL_ORDER_CACHE

        # Convert to string for lookup
        str_message_id = str(message_id)

        # Debug logging (only in log files)
        logger.debug(f"Looking for message ID {str_message_id} in cache")
        logger.debug(f"Available keys in cache: {list(GLOBAL_ORDER_CACHE.keys())}")

        # Direct lookup from global cache
        orders = GLOBAL_ORDER_CACHE.get(str_message_id)

        # Debug logging
        if orders:
            logger.debug(f"Found orders for message ID {str_message_id}")
            return orders
        else:
            logger.debug(f"No orders found for message ID {str_message_id}")
            return None

    def remove_order(self, message_id, order_id):
        """
        Remove a specific order from a message's orders list after it's been cancelled.

        Args:
            message_id: The message ID associated with the orders
            order_id: The specific order ID to remove

        Returns:
            bool: True if order was found and removed, False otherwise
        """
        global GLOBAL_ORDER_CACHE

        # Convert to string for consistency
        str_message_id = str(message_id)
        str_order_id = str(order_id)

        # Check if message exists in cache
        if str_message_id not in GLOBAL_ORDER_CACHE:
            logger.info(f"Message ID {str_message_id} not found in cache when trying to remove order {str_order_id}")
            return False

        # Get cached data
        message_data = GLOBAL_ORDER_CACHE[str_message_id]
        orders_list = message_data.get('orders', [])

        # Check if order is in the list
        if str_order_id in orders_list:
            # Remove it
            orders_list.remove(str_order_id)
            logger.info(f"Removed order {str_order_id} from message {str_message_id}")

            # If no orders left, remove the entire message entry
            if not orders_list:
                del GLOBAL_ORDER_CACHE[str_message_id]
                logger.info(f"Removed message {str_message_id} from cache as it has no more orders")
            else:
                # Update the orders list
                message_data['orders'] = orders_list
                GLOBAL_ORDER_CACHE[str_message_id] = message_data
                logger.info(f"Message {str_message_id} now has {len(orders_list)} orders")

            # Save changes to file
            self.save_cache()
            return True
        else:
            logger.info(f"Order {str_order_id} not found in message {str_message_id}")
            return False

    def remove_message(self, message_id):
        """
        Remove an entire message entry from the cache after all its orders are processed

        Args:
            message_id: The message ID to remove

        Returns:
            bool: True if message was found and removed, False otherwise
        """
        global GLOBAL_ORDER_CACHE

        # Convert to string for consistency
        str_message_id = str(message_id)

        # Check if message exists in cache
        if str_message_id in GLOBAL_ORDER_CACHE:
            # Remove the entry
            del GLOBAL_ORDER_CACHE[str_message_id]
            logger.info(f"Removed message {str_message_id} from cache")

            # Save changes to file
            self.save_cache()
            return True
        else:
            logger.info(f"Message ID {str_message_id} not found when trying to remove")
            return False

    def cleanup_old_entries(self, days=2):
        """
        Remove entries older than specified days
        """
        global GLOBAL_ORDER_CACHE

        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff_date.isoformat()

        keys_to_remove = []

        for message_id, data in GLOBAL_ORDER_CACHE.items():
            timestamp = data.get('timestamp')
            if timestamp and timestamp < cutoff_str:
                keys_to_remove.append(message_id)

        if keys_to_remove:
            for key in keys_to_remove:
                if key in GLOBAL_ORDER_CACHE:
                    del GLOBAL_ORDER_CACHE[key]

            logger.info(f"Removed {len(keys_to_remove)} old entries from order cache")
            self.save_cache()