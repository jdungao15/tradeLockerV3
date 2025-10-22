import logging
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class SignalValidator:
    """Validates trading signals before execution"""

    def __init__(self):
        # Maximum allowed slippage in pips for different instrument types
        self.max_slippage_pips = {
            'XAUUSD': float(os.getenv('MAX_SLIPPAGE_GOLD', 50)),  # Gold
            'FOREX': float(os.getenv('MAX_SLIPPAGE_FOREX', 10)),  # Forex pairs
            'DJI30': float(os.getenv('MAX_SLIPPAGE_INDICES', 100)),  # Indices
            'US30': float(os.getenv('MAX_SLIPPAGE_INDICES', 100)),
            'DEFAULT': float(os.getenv('MAX_SLIPPAGE_DEFAULT', 20))
        }
        # Maximum signal age in seconds
        self.max_signal_age = int(os.getenv('MAX_SIGNAL_AGE_SECONDS', 180))  # 3 minutes

    def _get_pip_value(self, instrument_name):
        """Determine pip value based on instrument"""
        instrument_upper = instrument_name.upper()

        # Japanese Yen pairs
        if instrument_upper.endswith("JPY") or "JPY" in instrument_upper:
            return 0.01

        # Indices
        if any(idx in instrument_upper for idx in ["DJI30", "DOW", "US30", "NAS100", "SPX500"]):
            return 1.0

        # Gold
        if any(gold in instrument_upper for gold in ["XAUUSD", "GOLD"]):
            return 0.1

        # Standard forex pairs
        return 0.0001

    def _get_max_slippage(self, instrument_name):
        """Get maximum allowed slippage for instrument"""
        instrument_upper = instrument_name.upper()

        # Check specific instruments first
        if any(gold in instrument_upper for gold in ["XAUUSD", "GOLD"]):
            return self.max_slippage_pips['XAUUSD']

        if any(idx in instrument_upper for idx in ["DJI30", "US30", "DOW"]):
            return self.max_slippage_pips['DJI30']

        # Check if it's a forex pair (6 characters, contains common currency codes)
        common_currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD']
        if len(instrument_name) == 6 and any(curr in instrument_upper for curr in common_currencies):
            return self.max_slippage_pips['FOREX']

        return self.max_slippage_pips['DEFAULT']

    async def validate_signal_before_execution(
            self,
            quotes_client,
            selected_account,
            instrument_data,
            parsed_signal,
            signal_timestamp=None
    ):
        """
        Validates if a signal is still valid for execution.

        Returns:
            dict: {
                'valid': bool,
                'reason': str (if invalid),
                'order_type': 'limit' or 'market',
                'adjusted_entry': float (if using market),
                'price_diff_pips': float
            }
        """
        try:
            instrument_name = instrument_data['name']
            signal_entry = parsed_signal['entry_point']
            signal_side = parsed_signal['order_type'].lower()

            # Check if this is originally a LIMIT order
            original_order_type = parsed_signal.get('order_type', '').lower()

            # Step 1: Check signal age if timestamp provided
            if signal_timestamp:
                age_seconds = (datetime.now() - signal_timestamp).total_seconds()
                if age_seconds > self.max_signal_age:
                    return {
                        'valid': False,
                        'reason': f'Signal too old ({age_seconds:.0f}s > {self.max_signal_age}s)'
                    }

            # Step 2: Get current market price
            quote = await quotes_client.get_quote_async(selected_account, instrument_name)

            if not quote or 'd' not in quote:
                logger.warning(f"Could not get quote for {instrument_name}. Allowing limit order.")
                return {
                    'valid': True,
                    'order_type': 'limit',
                    'reason': 'No quote available, using limit order'
                }

            # Extract bid/ask
            bid_price = float(quote['d'].get('bp', 0))
            ask_price = float(quote['d'].get('ap', 0))

            # Determine current execution price based on side
            current_price = ask_price if 'buy' in signal_side else bid_price

            # Step 3: Calculate price difference in pips
            pip_value = self._get_pip_value(instrument_name)
            price_diff = abs(signal_entry - current_price)
            price_diff_pips = price_diff / pip_value

            # Get maximum allowed slippage
            max_slippage = self._get_max_slippage(instrument_name)

            # Step 4: For LIMIT orders, allow them regardless of distance from current price
            # The provider is predicting future price movement, so distance is intentional
            if 'limit' in original_order_type:
                logger.debug(
                    "LIMIT order detected - allowing signal regardless of price distance "
                    f"({price_diff_pips:.1f} pips from current price)"
                )
                return {
                    'valid': True,
                    'order_type': 'limit',
                    'price_diff_pips': price_diff_pips,
                    'reason': 'LIMIT order - provider prediction'
                }

            # Step 5: For MARKET orders or when considering conversion, apply slippage validation

            # Determine if price moved favorably
            favorable_move = False
            if 'buy' in signal_side:
                favorable_move = current_price < signal_entry  # Can buy cheaper
            else:
                favorable_move = current_price > signal_entry  # Can sell higher

            # If price moved favorably OR very close to entry -> MARKET order
            if favorable_move or price_diff_pips <= 10:
                logger.info(
                    f"   ✓ Signal valid - Price favorable or close ({price_diff_pips:.1f} pips)"
                )
                return {
                    'valid': True,
                    'order_type': 'market',
                    'adjusted_entry': current_price,
                    'price_diff_pips': price_diff_pips,
                    'reason': 'Using MARKET order - favorable price'
                }

            # If within acceptable slippage range -> MARKET order
            elif price_diff_pips <= max_slippage:
                logger.info(
                    f"   ⚠ Signal valid but slipped {price_diff_pips:.1f} pips (max: {max_slippage}). Using MARKET order."
                )
                return {
                    'valid': True,
                    'order_type': 'market',
                    'adjusted_entry': current_price,
                    'price_diff_pips': price_diff_pips,
                    'reason': 'Using MARKET - within slippage tolerance'
                }

            # Too much slippage -> REJECT
            else:
                logger.warning(
                    f"   🚫 Signal rejected - Price moved {price_diff_pips:.1f} pips (max: {max_slippage} pips)"
                )
                return {
                    'valid': False,
                    'reason': f'Excessive slippage: {price_diff_pips:.1f} pips (max: {max_slippage})',
                    'price_diff_pips': price_diff_pips
                }

        except Exception as e:
            logger.error(f"Error validating signal: {e}", exc_info=True)
            # On error, allow limit order as fallback
            return {
                'valid': True,
                'order_type': 'limit',
                'reason': 'Validation error, defaulting to limit order'
            }
