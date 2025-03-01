Here's a section you can add to your README.md file explaining the new commands:

# Command Line Options

The trading bot provides several command line options to help manage Telegram channels and monitor system performance:

## Telegram Channel Management

### List Available Channels
Display all Telegram channels that the bot has access to, including their IDs and monitoring status:
```
python main.py --list-channels
```
This command shows a table with channel IDs, names, and indicates which channels are currently being monitored.

### Add a Channel to Monitoring
Start monitoring a specific Telegram channel for trading signals:
```
python main.py --add-channel CHANNEL_ID
```
Replace `CHANNEL_ID` with the numerical ID of the channel (e.g., `-1001234567890`).

### Remove a Channel from Monitoring
Stop monitoring a specific Telegram channel:
```
python main.py --remove-channel CHANNEL_ID
```
Replace `CHANNEL_ID` with the numerical ID of the channel you want to stop monitoring.

## Performance Monitoring

### Signal Parser Statistics
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

## Running the Bot

To start the bot with its default behavior (monitoring channels and processing signals):
```
python main.py
```

The bot will prompt you to select an account and then begin monitoring the configured channels for trading signals.

To stop the bot at any time, press `Ctrl+C`.