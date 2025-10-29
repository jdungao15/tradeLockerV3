# E8 Markets Web Automation Setup Guide

## 📋 Overview

This guide helps you set up and test web automation for E8 Markets platform.

## 🚀 Quick Start

### 1. Install Dependencies (if not already installed)

```bash
pip install selenium python-dotenv
```

### 2. Download ChromeDriver

Make sure ChromeDriver is installed and in your PATH:
- Download from: https://chromedriver.chromium.org/
- Or install via: `pip install webdriver-manager`

### 3. Configure Credentials

Add to your `.env` file:

```env
# E8 Markets Credentials
E8MARKETS_EMAIL=johnmiguel.dungao@gmail.com
E8MARKETS_PASSWORD=your_password_here
E8MARKETS_PARTNER_ID=2
```

### 4. Run the Test Script

```bash
python test_e8markets.py
```

## 🧪 What the Test Script Does

1. **Opens Browser** - Launches Chrome to the E8 Markets login page
2. **Analyzes Page Structure** - Identifies all forms, inputs, buttons
3. **Detects Patterns** - Checks for login forms, API endpoints, etc.
4. **Takes Screenshots** - Captures the page at different stages
5. **Attempts Login** - If password is provided, tries to log in
6. **Interactive Mode** - Lets you manually explore the platform

## 📸 Interactive Mode Commands

Once the browser opens, you can use these commands:

- `screenshot` - Take a screenshot
- `url` - Show current URL
- `analyze` - Re-analyze page structure
- `source` - Save page HTML source
- `help` - Show all commands
- `quit` - Close browser and exit

## 📊 Expected Output

```
🧪 E8 Markets API Tester
============================================================
📧 Email: johnmiguel.dungao@gmail.com
🔑 Password: ********
🔢 Partner ID: 2
============================================================

🚀 Initializing browser...
✅ Browser initialized

🌐 Navigating to: https://mtr.e8markets.com/...
✅ Current URL: [actual URL]
📄 Page Title: [page title]

🔍 Analyzing page structure...
📝 Found X input fields:
  1. Type: email, Name: email, ID: email-input
  2. Type: password, Name: password, ID: pwd
...

🔘 Found X buttons:
  1. Text: 'Login', Type: submit
...
```

## 🔧 Troubleshooting

### Issue: Browser doesn't open
**Solution:** Install ChromeDriver
```bash
pip install webdriver-manager
```

### Issue: "ChromeDriver not found"
**Solution:** Add ChromeDriver to PATH or specify location:
```python
from selenium.webdriver.chrome.service import Service
service = Service('/path/to/chromedriver')
driver = webdriver.Chrome(service=service, options=options)
```

### Issue: Page loads but can't find login form
**Possible reasons:**
- You might already be logged in (check cookies)
- The URL might include authentication tokens
- The platform might use a different auth flow

### Issue: Login fails
**Check:**
1. Password is correct in `.env` file
2. Account is not locked
3. No 2FA is required
4. Check screenshots for error messages

## 📁 Files Created

After running the test, you'll find:

```
screenshots/
  ├── e8_test_initial_page_[timestamp].png
  ├── e8_test_after_login_[timestamp].png
  └── e8_test_manual_[timestamp].png

page_source_[timestamp].html (if you use 'source' command)
```

## 🎯 Next Steps

Once you understand the page structure:

1. **Review the screenshots** to see what the interface looks like
2. **Check the page source** HTML file for element IDs and classes
3. **Note the selectors** that work for finding elements
4. **Update `e8markets_automation.py`** with the correct selectors

## 🔗 Main Automation Script

After testing, use `e8markets_automation.py` for actual trading:

```python
from e8markets_automation import E8MarketsAutomation

# Initialize
bot = E8MarketsAutomation(headless=False)

# Login
bot.initialize_browser()
bot.login()

# Select account
bot.select_broker_account(account_index=0)

# Place order
bot.place_order(
    instrument="EURUSD",
    order_type="limit",
    side="buy",
    volume=0.01,
    entry_price=1.0850,
    stop_loss=1.0800,
    take_profit=1.0900
)

# Get balance
balance = bot.get_account_balance()

# Close
bot.close()
```

## 🔒 Security Notes

- ✅ Never commit `.env` file with real credentials
- ✅ Use environment variables for sensitive data
- ✅ Test with demo accounts first
- ✅ Review all trades before executing
- ✅ Set up proper risk management

## 📞 Support

If you encounter issues:

1. Check the screenshots in `screenshots/` folder
2. Review the page source HTML
3. Look at browser console (F12) for JavaScript errors
4. Check the terminal output for error messages

## 🎮 Integration with Telegram Bot

To integrate with your existing Telegram trading bot:

```python
# In your main.py, add:
from e8markets_automation import E8MarketsAutomation

# After receiving a signal:
e8_bot = E8MarketsAutomation()
e8_bot.initialize_browser()
e8_bot.login()

# Place order based on Telegram signal
e8_bot.place_order(
    instrument=parsed_signal['instrument'],
    order_type=parsed_signal['order_type'],
    side='buy' if 'buy' in parsed_signal['order_type'] else 'sell',
    volume=position_size,
    entry_price=parsed_signal['entry_point'],
    stop_loss=parsed_signal['stop_loss'],
    take_profit=parsed_signal['take_profits'][0]
)
```

## ✅ Testing Checklist

- [ ] ChromeDriver installed
- [ ] Credentials added to `.env`
- [ ] Test script runs without errors
- [ ] Browser opens successfully
- [ ] Can see the E8 Markets page
- [ ] Screenshots are saved
- [ ] Login works (if password provided)
- [ ] Can access interactive mode
- [ ] Identified correct element selectors

---

**Last Updated:** 2025-01-28
**Version:** 1.0
