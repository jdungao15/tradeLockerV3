import re
from datetime import datetime, timedelta
import pytz
import logging

logger = logging.getLogger(__name__)


def calculate_text_similarity(text1, text2):
    """
    Calculate similarity between two text strings.

    Args:
        text1: First text string
        text2: Second text string

    Returns:
        float: Similarity score between 0 and 1
    """
    if not text1 or not text2:
        return 0

    # Convert to lowercase and split into words
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    # Filter out common words that don't add meaningful comparison value
    common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'if', 'then', 'is', 'it',
                    'this', 'that', 'to', 'for', 'with', 'in', 'on', 'at'}

    words1 = words1.difference(common_words)
    words2 = words2.difference(common_words)

    # Calculate Jaccard similarity
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))

    if union == 0:
        return 0

    return intersection / union


def extract_prices_from_text(text):
    """
    Extract price values from text.

    Args:
        text: Text to extract prices from

    Returns:
        list: List of extracted prices as floats
    """
    if not text:
        return []

    # Pattern to match prices (handles various formats)
    price_patterns = [
        r'\b(\d+\.\d+)\b',  # Standard decimal (1.2345)
        r'@\s*(\d+\.\d+)',  # @1.2345 format
        r'price\s*:?\s*(\d+\.\d+)',  # price: 1.2345
        r'entry\s*:?\s*(\d+\.\d+)',  # entry: 1.2345
        r'sl\s*:?\s*(\d+\.\d+)',  # sl: 1.2345
        r'tp\s*:?\s*(\d+\.\d+)'  # tp: 1.2345
    ]

    prices = []
    for pattern in price_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            try:
                price = float(match)
                prices.append(price)
            except ValueError:
                continue

    return prices


def estimate_message_timeframe(message):
    """
    Try to estimate the timeframe mentioned in a message.

    Args:
        message: Message text

    Returns:
        tuple: (mentioned_time, time_range_minutes)
    """
    if not message:
        return None, None

    message_lower = message.lower()

    # Check for time references
    time_references = {
        'hour ago': 60,
        'hours ago': None,  # Will extract number
        'minute ago': 1,
        'minutes ago': None,  # Will extract number
        'earlier today': 240,  # Rough estimate (4 hours)
        'this morning': 360,  # Rough estimate (6 hours)
        'yesterday': 1440,  # 24 hours
    }

    for reference, minutes in time_references.items():
        if reference in message_lower:
            if minutes is None:
                # Extract number for "X hours/minutes ago"
                pattern = r'(\d+)\s+' + reference
                match = re.search(pattern, message_lower)
                if match:
                    try:
                        extracted_num = int(match.group(1))
                        if 'hour' in reference:
                            minutes = extracted_num * 60
                        else:
                            minutes = extracted_num
                    except ValueError:
                        continue

            if minutes:
                # Calculate the referenced time
                mentioned_time = datetime.now(pytz.UTC) - timedelta(minutes=minutes)
                time_range = minutes // 2  # Half the mentioned time as range
                return mentioned_time, time_range

    # If no specific time reference is found
    return None, None


def match_signal_to_order_data(signal, orders_or_positions):
    """
    Match a signal to order data based on content.

    Args:
        signal: Signal data
        orders_or_positions: List of orders or positions

    Returns:
        tuple: (best_match, confidence_score)
    """
    if not signal or not orders_or_positions:
        return None, 0

    best_match = None
    best_score = 0

    for item in orders_or_positions:
        score = 0

        # Match instrument
        if signal.get('instrument') == item.get('instrument_name'):
            score += 30

        # Match direction (buy/sell)
        if signal.get('order_type') == item.get('side', '').lower():
            score += 20

        # Match price points (entry, stop loss, take profits)
        signal_prices = []
        if 'entry_point' in signal:
            signal_prices.append(float(signal['entry_point']))
        if 'stop_loss' in signal:
            signal_prices.append(float(signal['stop_loss']))
        if 'take_profits' in signal:
            signal_prices.extend([float(tp) for tp in signal['take_profits']])

        # Get order/position price
        item_price = None
        if 'price' in item:
            item_price = float(item['price'])
        elif 'entry_price' in item:
            item_price = float(item['entry_price'])

        if item_price and signal_prices:
            # Check if item price is close to any signal price
            for signal_price in signal_prices:
                price_diff_pct = abs(signal_price - item_price) / signal_price
                if price_diff_pct < 0.01:  # Within 1%
                    score += 25
                    break

        # Update best match if better score
        if score > best_score:
            best_score = score
            best_match = item

    # Calculate confidence (normalized score)
    max_possible_score = 75  # Sum of maximum scores
    confidence = best_score / max_possible_score if max_possible_score > 0 else 0

    return best_match, confidence


def is_time_related_instruction(message):
    """
    Check if message appears to be a time-sensitive instruction.

    Args:
        message: Message text

    Returns:
        bool: True if message appears to be time-sensitive
    """
    if not message:
        return False

    message_lower = message.lower()

    # Patterns suggesting time-sensitive instructions
    time_patterns = [
        r'close\s+now',
        r'take\s+profit\s+now',
        r'exit\s+now',
        r'move\s+sl\s+now',
        r'close\s+positions?\s+immediately',
        r'urgent',
        r'asap',
        r'quickly',
        r'don\'t\s+wait'
    ]

    return any(re.search(pattern, message_lower) for pattern in time_patterns)


def parse_management_details(message):
    """
    Parse detailed management instructions from a message.

    Args:
        message: Message text

    Returns:
        dict: Parsed management details
    """
    if not message:
        return {}

    message_lower = message.lower()
    details = {}

    # Check for specific percentage to close
    percentage_matches = re.findall(r'(\d+)%', message_lower)
    if percentage_matches:
        try:
            details['percentage'] = int(percentage_matches[0])
        except ValueError:
            pass

    # Check for specific price to move stop loss to
    sl_price_match = re.search(r'move\s+(?:sl|stop\s+loss)\s+to\s+(\d+\.\d+)', message_lower)
    if sl_price_match:
        try:
            details['new_sl_price'] = float(sl_price_match.group(1))
        except ValueError:
            pass

    # Check for trailing stop instructions
    if 'trailing' in message_lower or 'trail' in message_lower:
        details['trailing_stop'] = True

        # Try to extract trailing amount
        trail_match = re.search(r'trail(?:ing)?\s+(\d+)\s*(?:pips?|points?)', message_lower)
        if trail_match:
            try:
                details['trailing_amount'] = int(trail_match.group(1))
            except ValueError:
                pass

    return details