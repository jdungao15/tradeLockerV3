import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


class TradingBotFormatter(logging.Formatter):
    """Custom formatter for the trading bot logs with color coding"""

    def __init__(self, use_colors=True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()  # Only use colors for terminal output

        # ANSI color codes
        self.reset = "\033[0m" if self.use_colors else ""

        # Level colors
        self.colors = {
            logging.DEBUG: "\033[38;5;39m",  # Light blue
            logging.INFO: "\033[38;5;34m",  # Green
            logging.WARNING: "\033[38;5;214m",  # Orange
            logging.ERROR: "\033[38;5;196m",  # Red
            logging.CRITICAL: "\033[48;5;196m\033[38;5;15m",  # White on red background
        }

        # Component colors (for different modules)
        self.component_colors = {
            "trading_bot": "\033[38;5;51m",  # Cyan
            "tradelocker_api": "\033[38;5;33m",  # Blue
            "services.drawdown_manager": "\033[38;5;141m",  # Light purple
            "services.pos_monitor": "\033[38;5;46m",  # Bright green
            "services.order_handler": "\033[38;5;118m",  # Light green
            "core.signal_parser": "\033[38;5;220m",  # Yellow
            "core.risk_management": "\033[38;5;208m",  # Orange
        }

        # Default component color
        self.default_component_color = "\033[38;5;250m"  # Light gray

    def get_component_color(self, name):
        """Get the appropriate color for a component based on its name"""
        if not self.use_colors:
            return ""

        # Find the most specific match
        matching_component = None
        for comp in self.component_colors:
            if name.startswith(comp) and (matching_component is None or len(comp) > len(matching_component)):
                matching_component = comp

        return self.component_colors.get(matching_component, self.default_component_color)

    def format(self, record):
        # Format timestamp (without microseconds)
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")

        # Get appropriate colors
        level_color = self.colors.get(record.levelno, "") if self.use_colors else ""
        component_color = self.get_component_color(record.name)

        # Create log message
        level_name = f"{record.levelname:<8}"
        component_name = f"{record.name:<30}"

        # Build the formatted message with colors
        formatted_message = (
            f"{level_color}{timestamp}{self.reset} - "
            f"{component_color}{component_name}{self.reset} - "
            f"{level_color}{level_name}{self.reset} - "
            f"{record.getMessage()}"
        )

        # Add exception info if present
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            formatted_message += f"\n{exception_text}"

        return formatted_message


def setup_logging():
    """Configure logging for the trading bot application with UTF-8 emoji support"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Force console to use UTF-8 encoding for emoji support (especially on Windows)
    try:
        # Reconfigure stdout to UTF-8 (Python 3.7+)
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        # Fallback for older Python versions
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')

    # Create console handler with color formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(TradingBotFormatter(use_colors=True))
    root_logger.addHandler(console_handler)

    # Create file handler for all logs with UTF-8 encoding
    main_file_handler = RotatingFileHandler(
        "logs/trading_bot.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'  # ⭐ ADDED - Enables emoji support
    )
    main_file_handler.setLevel(logging.INFO)
    main_file_handler.setFormatter(TradingBotFormatter(use_colors=False))
    root_logger.addHandler(main_file_handler)

    # Create separate file handler for errors with UTF-8 encoding
    error_file_handler = RotatingFileHandler(
        "logs/errors.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'  # ⭐ ADDED - Enables emoji support
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(TradingBotFormatter(use_colors=False))
    root_logger.addHandler(error_file_handler)

    # Create debug file handler for more verbose logs with UTF-8 encoding
    debug_file_handler = RotatingFileHandler(
        "logs/debug.log",
        maxBytes=20 * 1024 * 1024,  # 20 MB
        backupCount=3,
        encoding='utf-8'  # ⭐ ADDED - Enables emoji support
    )
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(TradingBotFormatter(use_colors=False))
    root_logger.addHandler(debug_file_handler)

    # Customize specific loggers
    customize_component_loggers()
    return root_logger


def customize_component_loggers():
    """Customize log levels for specific components"""
    # Set more verbose logging for specific components
    logging.getLogger("trading_bot").setLevel(logging.INFO)
    logging.getLogger("core.signal_parser").setLevel(logging.DEBUG)
    logging.getLogger("services.pos_monitor").setLevel(logging.INFO)

    # Set less verbose logging for noisy components
    logging.getLogger("tradelocker_api.api_client").setLevel(logging.WARNING)


# To implement this in your TradingBot class:
def _setup_logging(self):
    """Configure logging for the application"""
    # Set up the enhanced logging system
    setup_logging()

    # Set the instance logger
    self.logger = logging.getLogger("trading_bot")


class EnhancedTradingFormatter(logging.Formatter):
    """Enhanced formatter for trading bot logs with better color coding and readability"""

    def __init__(self, use_colors=True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()  # Only use colors for terminal output

        # ANSI color codes
        self.reset = "\033[0m" if self.use_colors else ""

        # Level colors
        self.colors = {
            logging.DEBUG: "\033[38;5;39m",  # Light blue
            logging.INFO: "\033[38;5;34m",  # Green
            logging.WARNING: "\033[38;5;214m",  # Orange
            logging.ERROR: "\033[38;5;196m",  # Red
            logging.CRITICAL: "\033[48;5;196m\033[38;5;15m",  # White on red background
        }

        # Component colors with brighter, more distinct colors
        self.component_colors = {
            "trading_bot": "\033[38;5;51m",  # Bright cyan
            "tradelocker_api": "\033[38;5;33m",  # Blue
            "services.drawdown_manager": "\033[38;5;141m",  # Light purple
            "services.pos_monitor": "\033[38;5;46m",  # Bright green
            "services.order_handler": "\033[38;5;118m",  # Light green
            "core.signal_parser": "\033[38;5;220m",  # Yellow
            "core.risk_management": "\033[38;5;208m",  # Orange
        }

        # Message type highlights (for special message types)
        self.highlights = {
            "MARKET ORDER": "\033[48;5;27m\033[38;5;15m",  # White on blue
            "LIMIT ORDER": "\033[48;5;28m\033[38;5;15m",  # White on green
            "SUCCESS": "\033[48;5;28m\033[38;5;15m",  # White on green
            "FAILED": "\033[48;5;160m\033[38;5;15m",  # White on red
            "WARNING": "\033[48;5;214m\033[38;5;0m",  # Black on orange
        }

        # Default component color
        self.default_component_color = "\033[38;5;250m"  # Light gray

    def get_component_color(self, name):
        """Get the appropriate color for a component based on its name"""
        if not self.use_colors:
            return ""

        # Find the most specific match
        matching_component = None
        for comp in self.component_colors:
            if name.startswith(comp) and (matching_component is None or len(comp) > len(matching_component)):
                matching_component = comp

        return self.component_colors.get(matching_component, self.default_component_color)

    def highlight_keywords(self, message):
        """Add background highlighting to important keywords"""
        if not self.use_colors:
            return message

        for keyword, color in self.highlights.items():
            if keyword in message:
                message = message.replace(keyword, f"{color}{keyword}{self.reset}")

        return message

    def format(self, record):
        # Format timestamp (with cleaner format)
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")

        # Get appropriate colors
        level_color = self.colors.get(record.levelno, "") if self.use_colors else ""
        component_color = self.get_component_color(record.name)

        # Create log message
        level_name = f"{record.levelname:<8}"
        component_name = f"{record.name:<30}"

        # Get the message and highlight keywords
        message = self.highlight_keywords(record.getMessage())

        # Add nice separator for better readability between log entries
        if record.levelno >= logging.WARNING:
            separator = f"\n{level_color}{'=' * 100}{self.reset}\n"
        else:
            separator = ""

        # Build the formatted message with colors
        formatted_message = (
            f"{separator}"
            f"{level_color}{timestamp}{self.reset} | "
            f"{component_color}{component_name}{self.reset} | "
            f"{level_color}{level_name}{self.reset} | "
            f"{message}"
        )

        # Add exception info if present
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            formatted_message += f"\n{exception_text}"

        return formatted_message