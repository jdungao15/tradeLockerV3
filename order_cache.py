import json
import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Global static memory cache that persists across instances
GLOBAL_ORDER_CACHE = {}


class OrderCache:
    """
    Enhanced cache with memory-first approach that persists across restarts,
    handles order deletion after successful cancellation, and provides
    content-based matching for forwarded signals
    """

    def __init__(self, cache_file='order_cache.json'):
        self.cache_file = cache_file
        # Use the global cache for in-memory storage
        global GLOBAL_ORDER_CACHE

        # Load from file only if global cache is empty
        if not GLOBAL_ORDER_CACHE:
            self.load_cache()
        else:
            logger.info(f"Using existing in-memory cache with {len(GLOBAL_ORDER_CACHE)} entries")

    def load_cache(self):
        """Load cache from file into global memory"""
        global GLOBAL_ORDER_CACHE

        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    loaded_data = json.load(f)

                # Update global cache
                GLOBAL_ORDER_CACHE.update(loaded_data)

                logger.info(f"Loaded order cache with {len(GLOBAL_ORDER_CACHE)} entries")
                logger.info(f"Cache keys: {list(GLOBAL_ORDER_CACHE.keys())}")
            else:
                logger.info("No order cache file found. Starting with empty cache.")
                # Save empty cache to create the file
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

            logger.info(f"Saved order cache with {len(GLOBAL_ORDER_CACHE)} entries")
            return True
        except Exception as e:
            logger.error(f"Error saving order cache: {e}")
            return False

    def store_orders(self, message_id, order_ids, take_profits, instrument=None, entry_price=None, stop_loss=None):
        """
        Store order IDs with message ID, take profits, entry price, and stop loss in global memory

        Args:
            message_id: Telegram message ID (will be converted to string)
            order_ids: List of order IDs
            take_profits: List of take profit levels
            instrument: Optional instrument name
            entry_price: Entry price for breakeven functionality
            stop_loss: Stop loss price for content matching
        """
        global GLOBAL_ORDER_CACHE

        if not message_id or not order_ids:
            logger.warning(f"Cannot store orders: missing message_id ({message_id}) or order_ids ({order_ids})")
            return False

        # Ensure message_id is a string for consistency
        str_message_id = str(message_id)

        # Log detailed information
        logger.info(f"Storing orders for message_id: '{str_message_id}' with {len(order_ids)} orders")

        # Ensure order_ids are strings
        str_order_ids = [str(order_id) for order_id in order_ids]

        # Store in global cache first
        GLOBAL_ORDER_CACHE[str_message_id] = {
            'orders': str_order_ids,
            'take_profits': take_profits,
            'instrument': instrument,
            'entry_price': entry_price,  # Store entry price
            'stop_loss': stop_loss,  # Store stop loss
            'timestamp': datetime.now().isoformat()
        }

        # Verify storage
        verify = str_message_id in GLOBAL_ORDER_CACHE
        logger.info(f"Verification: message_id {str_message_id} in memory cache: {verify}")

        # Log current keys
        logger.info(f"Cache updated, current keys: {list(GLOBAL_ORDER_CACHE.keys())}")

        # Save to file as backup
        return self.save_cache()

    def get_orders(self, message_id):
        """
        Get orders associated with a message ID directly from global memory
        """
        global GLOBAL_ORDER_CACHE

        # Convert to string for lookup
        str_message_id = str(message_id)

        logger.info(f"Looking for message ID {str_message_id} in cache")
        logger.info(f"Available keys in cache: {list(GLOBAL_ORDER_CACHE.keys())}")

        # Direct lookup from global cache
        orders = GLOBAL_ORDER_CACHE.get(str_message_id)

        # Log result
        if orders:
            logger.info(f"Found orders for message ID {str_message_id}")
            return orders
        else:
            logger.info(f"No orders found for message ID {str_message_id}")
            return None

    def find_orders_by_content(self, instrument=None, entry_price=None, stop_loss=None, take_profits=None,
                               max_age_hours=24):
        """
        Find orders by content matching when message ID matching fails.
        Scores potential matches and returns the best match.

        Args:
            instrument: Instrument name to match
            entry_price: Entry price to match (with tolerance)
            stop_loss: Stop loss to match (with tolerance)
            take_profits: Take profits to match (with tolerance)
            max_age_hours: Maximum age of cached orders to consider

        Returns:
            tuple: (message_id, order_data) of best matching order or (None, None) if no match
        """
        global GLOBAL_ORDER_CACHE

        if not instrument:
            return None, None

        logger.info(
            f"Attempting to find orders by content: instrument={instrument}, entry={entry_price}, stop={stop_loss}")

        # Define matching parameters
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        cutoff_str = cutoff_time.isoformat()

        # Tolerances for price matching (adjust as needed)
        entry_tolerance = 0.0010  # 10 pips for forex
        sl_tolerance = 0.0010  # 10 pips for forex
        tp_tolerance = 0.0015  # 15 pips for forex

        # Special tolerances for indices and gold
        if instrument and ('DJI' in instrument.upper() or 'US30' in instrument.upper() or 'DOW' in instrument.upper()):
            entry_tolerance = 10.0  # 10 points for US30/DJI30
            sl_tolerance = 10.0
            tp_tolerance = 15.0
        elif instrument and ('NDX' in instrument.upper() or 'NAS' in instrument.upper()):
            entry_tolerance = 20.0  # 20 points for NASDAQ
            sl_tolerance = 20.0
            tp_tolerance = 30.0
        elif instrument and ('XAU' in instrument.upper() or 'GOLD' in instrument.upper()):
            entry_tolerance = 1.0  # 10 points for Gold
            sl_tolerance = 1.0
            tp_tolerance = 1.5

        best_match = None
        best_score = 0
        best_message_id = None

        # Scan all cached orders
        for msg_id, order_data in GLOBAL_ORDER_CACHE.items():
            # Skip old entries
            timestamp = order_data.get('timestamp', '2000-01-01')
            if timestamp < cutoff_str:
                continue

            # Initialize match score
            score = 0

            # Match instrument (highest priority)
            cached_instrument = order_data.get('instrument')
            if not cached_instrument:
                continue

            # If instrument matches exactly, add high score
            if cached_instrument.upper() == instrument.upper():
                score += 50
            # If instrument is a partial match (e.g. "GOLD" vs "XAUUSD")
            elif any(term in cached_instrument.upper() for term in instrument.upper().split()) or \
                    any(term in instrument.upper() for term in cached_instrument.upper().split()):
                score += 30
            else:
                # No instrument match, skip this entry
                continue

            # Match entry price if provided
            if entry_price is not None and order_data.get('entry_price') is not None:
                cached_entry = float(order_data['entry_price'])
                if abs(cached_entry - entry_price) <= entry_tolerance:
                    # Score higher for closer matches
                    closeness = 1.0 - (abs(cached_entry - entry_price) / entry_tolerance)
                    score += 25 * closeness

            # Match stop loss if provided
            if stop_loss is not None and order_data.get('stop_loss') is not None:
                cached_sl = float(order_data['stop_loss'])
                if abs(cached_sl - stop_loss) <= sl_tolerance:
                    # Score higher for closer matches
                    closeness = 1.0 - (abs(cached_sl - stop_loss) / sl_tolerance)
                    score += 15 * closeness

            # Match take profits if provided
            if take_profits and order_data.get('take_profits'):
                cached_tps = order_data['take_profits']
                # If lengths match, check individual TPs
                if len(take_profits) == len(cached_tps):
                    tp_matches = 0
                    for i, tp in enumerate(take_profits):
                        if i < len(cached_tps) and abs(float(cached_tps[i]) - float(tp)) <= tp_tolerance:
                            tp_matches += 1

                    if tp_matches > 0:
                        score += 10 * (tp_matches / len(take_profits))

                # Even if lengths don't match, try to find any matching TP
                elif len(take_profits) > 0 and len(cached_tps) > 0:
                    for tp in take_profits:
                        for cached_tp in cached_tps:
                            if abs(float(cached_tp) - float(tp)) <= tp_tolerance:
                                score += 5
                                break

            # If this is the best match so far, update
            if score > best_score:
                best_score = score
                best_match = order_data
                best_message_id = msg_id

        # Require a minimum score to consider it a match
        min_required_score = 50  # Instrument match at minimum
        if best_score >= min_required_score:
            logger.info(f"Found content match with message_id {best_message_id}, score: {best_score}")
            return best_message_id, best_match

        logger.info(f"No content match found (best score: {best_score})")
        return None, None

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