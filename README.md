# Forex Trading Bot

An automated trading bot that monitors Telegram channels for trading signals and executes trades on the TradeLocker platform with risk management and news filtering.

## Features

- **Telegram Signal Monitoring**: Automatically detects and parses trading signals from configured Telegram channels
- **Automatic Order Execution**: Places orders with proper risk management on your TradeLocker account
- **Position Monitoring**: Tracks open positions and manages trailing stop losses
- **Risk Management**: Calculates optimal position sizes based on account balance and risk percentage
- **Drawdown Control**: Implements daily drawdown limits to protect your account
- **News Event Filtering**: Prevents trading during high-impact economic news events
- **Asynchronous Architecture**: Efficiently handles multiple operations simultaneously

## Requirements

- Python 3.8 or higher
- TradeLocker account credentials
- Telegram API credentials

## Installation

1. Clone the repository:
```
git clone https://github.com/yourusername/forex-trading-bot.git
cd forex-trading-bot
```

2. Install the dependencies:
```
pip install -r requirements.txt
```

3. Set up environment variables by creating a `.env` file with the following:
```
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
TRADELOCKER_API_URL=your_tradelocker_api_url
TRADELOCKER_EMAIL=your_tradelocker_email
TRADELOCKER_PASSWORD=your_tradelocker_password
TRADELOCKER_SERVER=your_tradelocker_server
OPENAI_API_KEY=your_openai_api_key
ENABLE_POSITION_MONITOR=true
ENABLE_SIGNAL_PROCESSING=true
ENABLE_NEWS_FILTER=true
```

## Command Line Options

The trading bot provides several command line options to help manage Telegram channels and monitor system performance:

### Telegram Channel Management

#### List Available Channels
Display all Telegram channels that the bot has access to, including their IDs and monitoring status:
```
python main.py --list-channels
```
This command shows a table with channel IDs, names, and indicates which channels are currently being monitored.

#### Add a Channel to Monitoring
Start monitoring a specific Telegram channel for trading signals:
```
python main.py --add-channel CHANNEL_ID
```
Replace `CHANNEL_ID` with the numerical ID of the channel (e.g., `-1001234567890`).

#### Remove a Channel from Monitoring
Stop monitoring a specific Telegram channel:
```
python main.py --remove-channel CHANNEL_ID
```
Replace `CHANNEL_ID` with the numerical ID of the channel you want to stop monitoring.

### Performance Monitoring

#### Signal Parser Statistics
View performance metrics for the signal parsing system:
```
python main.py --parser-stats
```
This displays statistics such as:
- Number of signals processed
- Cache hit rate
- Success rate of regex-based parsing vs. API calls
- Average processing times
- Estimated cost savings

## News Event Filtering

The bot implements PropFirm trading rule 2.5.2 which prohibits trading 30 minutes before and after high-impact news events. To check upcoming news events or test the news filter:

### Viewing Economic Calendar Events
```bash
# Display all upcoming events for today
python tools/news_check.py list --today

# Display only high-impact events for today
python tools/news_check.py list --today --impact high

# Display all events for the current week, sorted by impact level
python tools/news_check.py list --week --sort-impact

# Display only high-impact events for the next 7 days
python tools/news_check.py list --hours 168 --impact high

# Display a summary of events (country and impact only)
python tools/news_check.py list --week --summary

# Display debug information about event counts
python tools/news_check.py list --week --debug
```

### Analyzing Economic Calendar Data
Use the debug script to analyze your economic events CSV file:
```bash
python tools/debug_news.py economic_events.csv
```
This will display:
- The number of events per date
- Distribution of impact levels by date
- Date format consistency checks

You can disable the news filter by setting `ENABLE_NEWS_FILTER=false` in your `.env` file.

## Running the Bot

To start the bot with its default behavior:
```
python main.py
```

The bot will:
1. Connect to your TradeLocker account
2. Prompt you to select a trading account
3. Display upcoming high-impact news events
4. Begin monitoring the configured Telegram channels for trading signals
5. Process signals and place trades according to your risk management settings

To stop the bot at any time, press `Ctrl+C`.

## Project Structure

- `main.py`: Main entry point and bot implementation
- `core/`: Core functionality modules
  - `signal_parser.py`: Parses trading signals from text messages
  - `risk_management.py`: Calculates position sizes and manages risk
- `services/`: Service modules
  - `news_filter.py`: Filters trades based on economic calendar events
  - `order_handler.py`: Handles order placement and management
  - `pos_monitor.py`: Monitors and manages open positions
  - `drawdown_manager.py`: Manages daily drawdown limits
- `tradelocker_api/`: API client modules for TradeLocker
- `tools/`: Utility tools
  - `news_check.py`: Command-line tool to check news events
  - `debug_news.py`: Tool for analyzing economic calendar data

## PropFirm Rules Compliance

This bot is designed to comply with typical PropFirm trading rules, including:

- **Rule 2.5.2**: No trading 30 minutes before and after high-impact news events (implemented via the news filter)
- **Daily Drawdown Limits**: Prevents trading if daily drawdown limit is reached
- **Risk Management**: Calculates proper position sizes based on account balance

## Troubleshooting

### News Event Filtering Issues
If you're experiencing issues with the news filter:

1. Check if your economic_events.csv file is up to date:
```
python tools/news_check.py list --debug
```

2. Analyze your CSV file format and content:
```
python tools/debug_news.py economic_events.csv
```

3. Make sure timezones are configured correctly in your environment.

### Common Error Messages

- "NewsEventFilter object has no attribute 'can_place_order'": Update your news_filter.py file with the latest version.
- "Order cannot be created since trading out of session is forbidden": This error occurs when trying to place trades outside market hours.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

Trading forex involves significant risk of loss and is not suitable for all investors. This software is provided for educational purposes only and does not constitute financial advice. Use at your own risk.