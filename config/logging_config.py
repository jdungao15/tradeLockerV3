import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler


class CleanConsoleFormatter(logging.Formatter):
    """Clean formatter for console - shows only the message, no technical details"""

    def format(self, record):
        # Just return the message - clean and simple
        message = record.getMessage()

        # Add exception info if present (for errors)
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            message += f"\n{exception_text}"

        return message


class DetailedFileFormatter(logging.Formatter):
    """Detailed formatter for log files - includes all technical information"""

    def __init__(self):
        super().__init__()

    def format(self, record):
        # Format timestamp (without microseconds)
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")

        # Create log message
        level_name = f"{record.levelname:<8}"
        component_name = f"{record.name:<30}"

        # Build the formatted message for files
        formatted_message = (
            f"{timestamp} - "
            f"{component_name} - "
            f"{level_name} - "
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

    # Create console handler with CLEAN formatter (no module names, no timestamps, no log levels)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(CleanConsoleFormatter())
    root_logger.addHandler(console_handler)

    # Create file handler for all logs with DETAILED formatter and UTF-8 encoding
    main_file_handler = RotatingFileHandler(
        "logs/trading_bot.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    main_file_handler.setLevel(logging.INFO)
    main_file_handler.setFormatter(DetailedFileFormatter())
    root_logger.addHandler(main_file_handler)

    # Create separate file handler for errors with UTF-8 encoding
    error_file_handler = RotatingFileHandler(
        "logs/errors.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(DetailedFileFormatter())
    root_logger.addHandler(error_file_handler)

    # Create debug file handler for more verbose logs with UTF-8 encoding
    debug_file_handler = RotatingFileHandler(
        "logs/debug.log",
        maxBytes=20 * 1024 * 1024,  # 20 MB
        backupCount=3,
        encoding='utf-8'
    )
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(DetailedFileFormatter())
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


def log_trade_execution(logger, message):
    """
    Helper function to log trade execution messages with timestamp.
    Use this for important trade-related actions.

    Args:
        logger: The logger instance
        message: The message to log
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] {message}")