#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E8 Markets Web Automation Script
Automates trading on E8 Markets platform using Selenium
"""
import os
import sys
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/e8markets_automation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class E8MarketsAutomation:
    """Automation class for E8 Markets trading platform"""

    def __init__(self, headless: bool = False):
        """
        Initialize E8 Markets automation

        Args:
            headless: Run browser in headless mode
        """
        self.driver = None
        self.headless = headless
        self.wait_timeout = 15

        # E8 Markets credentials from environment
        self.email = os.getenv('E8MARKETS_EMAIL', 'johnmiguel.dungao@gmail.com')
        self.password = os.getenv('E8MARKETS_PASSWORD')
        self.partner_id = os.getenv('E8MARKETS_PARTNER_ID', '2')

        # Base URLs
        self.login_url = f"https://mtr.e8markets.com/match-trader-edge/multi-broker-access/available-brokers/login?partnerId={self.partner_id}&email={self.email}"
        self.dashboard_url = "https://mtr.e8markets.com/match-trader-edge/dashboard"

        # Trading state
        self.is_logged_in = False
        self.selected_account = None

    def initialize_browser(self):
        """Initialize Chrome browser with optimal settings"""
        try:
            chrome_options = Options()

            # Browser settings
            if self.headless:
                chrome_options.add_argument('--headless')

            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')

            # User agent
            chrome_options.add_argument(
                'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )

            # Disable automation detection
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            # Initialize driver
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.set_page_load_timeout(30)

            # Hide webdriver flag
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })

            logger.info("✅ Browser initialized successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to initialize browser: {e}")
            return False

    def login(self) -> bool:
        """
        Login to E8 Markets platform

        Returns:
            bool: True if login successful
        """
        try:
            logger.info(f"🔐 Logging in to E8 Markets...")
            logger.info(f"📧 Email: {self.email}")

            # Navigate to login page
            self.driver.get(self.login_url)
            time.sleep(3)

            logger.info(f"🌐 Current URL: {self.driver.current_url}")

            # Check if already logged in (redirected to dashboard)
            if "dashboard" in self.driver.current_url.lower():
                logger.info("✅ Already logged in!")
                self.is_logged_in = True
                return True

            # Wait for page to load
            WebDriverWait(self.driver, self.wait_timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Try to find password field (common login patterns)
            password_selectors = [
                (By.ID, "password"),
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.XPATH, "//input[@type='password']")
            ]

            password_field = None
            for by, selector in password_selectors:
                try:
                    password_field = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((by, selector))
                    )
                    logger.info(f"✅ Found password field using: {by}={selector}")
                    break
                except TimeoutException:
                    continue

            if not password_field:
                logger.warning("⚠️ No password field found - might already be at broker selection")
                self.take_screenshot("no_password_field")

                # Check if we're at broker selection page
                if self.wait_for_broker_selection():
                    self.is_logged_in = True
                    return True

                return False

            # Enter password
            if self.password:
                password_field.clear()
                password_field.send_keys(self.password)
                logger.info("✅ Password entered")
                time.sleep(1)

                # Find and click login button
                login_button_selectors = [
                    (By.CSS_SELECTOR, "button[type='submit']"),
                    (By.XPATH, "//button[contains(text(), 'Login')]"),
                    (By.XPATH, "//button[contains(text(), 'Sign In')]"),
                    (By.ID, "login-button"),
                    (By.CLASS_NAME, "btn-login")
                ]

                for by, selector in login_button_selectors:
                    try:
                        login_button = self.driver.find_element(by, selector)
                        login_button.click()
                        logger.info("✅ Login button clicked")
                        break
                    except NoSuchElementException:
                        continue

                # Wait for redirect
                time.sleep(5)

            # Verify login success
            if "dashboard" in self.driver.current_url.lower() or self.wait_for_broker_selection():
                logger.info("✅ Login successful!")
                self.is_logged_in = True
                self.take_screenshot("login_success")
                return True
            else:
                logger.error("❌ Login failed - unexpected page")
                self.take_screenshot("login_failed")
                return False

        except Exception as e:
            logger.error(f"❌ Login error: {e}", exc_info=True)
            self.take_screenshot("login_error")
            return False

    def wait_for_broker_selection(self, timeout: int = 10) -> bool:
        """Check if we're at broker selection page"""
        try:
            # Look for common broker selection elements
            broker_selectors = [
                (By.XPATH, "//div[contains(text(), 'broker')]"),
                (By.XPATH, "//button[contains(text(), 'Select')]"),
                (By.CLASS_NAME, "broker-list"),
                (By.ID, "broker-selection")
            ]

            for by, selector in broker_selectors:
                try:
                    WebDriverWait(self.driver, timeout).until(
                        EC.presence_of_element_located((by, selector))
                    )
                    logger.info("✅ Broker selection page detected")
                    return True
                except TimeoutException:
                    continue

            return False
        except Exception:
            return False

    def select_broker_account(self, account_index: int = 0) -> bool:
        """
        Select a broker account from available options

        Args:
            account_index: Index of account to select (default: first account)

        Returns:
            bool: True if successful
        """
        try:
            logger.info(f"🏦 Selecting broker account (index: {account_index})...")

            # Wait for account list to load
            time.sleep(3)

            # Common patterns for account selection
            account_selectors = [
                (By.CSS_SELECTOR, ".account-item"),
                (By.CSS_SELECTOR, ".broker-account"),
                (By.XPATH, "//div[contains(@class, 'account')]"),
                (By.CSS_SELECTOR, "button.select-account")
            ]

            accounts = None
            for by, selector in account_selectors:
                try:
                    accounts = self.driver.find_elements(by, selector)
                    if accounts:
                        logger.info(f"✅ Found {len(accounts)} accounts")
                        break
                except:
                    continue

            if not accounts or len(accounts) == 0:
                logger.warning("⚠️ No accounts found")
                self.take_screenshot("no_accounts")
                return False

            # Select specified account
            if account_index < len(accounts):
                accounts[account_index].click()
                logger.info(f"✅ Selected account at index {account_index}")
                time.sleep(3)

                self.take_screenshot("account_selected")
                return True
            else:
                logger.error(f"❌ Account index {account_index} out of range")
                return False

        except Exception as e:
            logger.error(f"❌ Error selecting account: {e}", exc_info=True)
            self.take_screenshot("account_selection_error")
            return False

    def place_order(
        self,
        instrument: str,
        order_type: str,
        side: str,
        volume: float,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> bool:
        """
        Place a trading order

        Args:
            instrument: Trading instrument (e.g., "EURUSD", "XAUUSD")
            order_type: Order type ("market", "limit", "stop")
            side: Trade side ("buy" or "sell")
            volume: Trade volume in lots
            entry_price: Entry price (for limit/stop orders)
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            bool: True if order placed successfully
        """
        try:
            logger.info(f"📊 Placing order: {instrument} {side.upper()} {volume} lots")

            # Look for "New Order" button
            new_order_selectors = [
                (By.XPATH, "//button[contains(text(), 'New Order')]"),
                (By.ID, "new-order-btn"),
                (By.CLASS_NAME, "btn-new-order"),
                (By.CSS_SELECTOR, "button.create-order")
            ]

            for by, selector in new_order_selectors:
                try:
                    new_order_btn = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((by, selector))
                    )
                    new_order_btn.click()
                    logger.info("✅ Opened new order dialog")
                    time.sleep(2)
                    break
                except TimeoutException:
                    continue

            # Select instrument
            self._fill_order_field("instrument", instrument)

            # Select order type
            self._fill_order_field("order_type", order_type)

            # Select side (buy/sell)
            self._click_button(side.lower())

            # Enter volume
            self._fill_order_field("volume", str(volume))

            # Enter prices if provided
            if entry_price and order_type != "market":
                self._fill_order_field("price", str(entry_price))

            if stop_loss:
                self._fill_order_field("stop_loss", str(stop_loss))

            if take_profit:
                self._fill_order_field("take_profit", str(take_profit))

            time.sleep(1)

            # Submit order
            submit_selectors = [
                (By.XPATH, "//button[contains(text(), 'Submit')]"),
                (By.XPATH, "//button[contains(text(), 'Place Order')]"),
                (By.ID, "submit-order"),
                (By.CSS_SELECTOR, "button[type='submit']")
            ]

            for by, selector in submit_selectors:
                try:
                    submit_btn = self.driver.find_element(by, selector)
                    submit_btn.click()
                    logger.info("✅ Order submitted")
                    time.sleep(2)
                    break
                except NoSuchElementException:
                    continue

            # Verify order placement
            self.take_screenshot("order_placed")
            logger.info("✅ Order placement completed")
            return True

        except Exception as e:
            logger.error(f"❌ Error placing order: {e}", exc_info=True)
            self.take_screenshot("order_error")
            return False

    def _fill_order_field(self, field_name: str, value: str):
        """Helper to fill order form fields"""
        selectors = [
            (By.ID, field_name),
            (By.NAME, field_name),
            (By.CSS_SELECTOR, f"input[name='{field_name}']"),
            (By.CSS_SELECTOR, f"select[name='{field_name}']"),
            (By.XPATH, f"//input[@placeholder='{field_name}']")
        ]

        for by, selector in selectors:
            try:
                field = self.driver.find_element(by, selector)
                field.clear()
                field.send_keys(value)
                logger.debug(f"Filled field {field_name}: {value}")
                return True
            except:
                continue

        logger.warning(f"⚠️ Could not find field: {field_name}")
        return False

    def _click_button(self, button_text: str):
        """Helper to click buttons by text"""
        try:
            button = self.driver.find_element(
                By.XPATH,
                f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{button_text.lower()}')]"
            )
            button.click()
            logger.debug(f"Clicked button: {button_text}")
            return True
        except:
            logger.warning(f"⚠️ Could not find button: {button_text}")
            return False

    def get_account_balance(self) -> Optional[float]:
        """Get current account balance"""
        try:
            balance_selectors = [
                (By.ID, "account-balance"),
                (By.CLASS_NAME, "balance"),
                (By.XPATH, "//span[contains(text(), 'Balance')]/following-sibling::span"),
                (By.CSS_SELECTOR, ".account-info .balance")
            ]

            for by, selector in balance_selectors:
                try:
                    balance_element = self.driver.find_element(by, selector)
                    balance_text = balance_element.text
                    # Extract numeric value
                    balance = float(''.join(filter(lambda x: x.isdigit() or x == '.', balance_text)))
                    logger.info(f"💰 Account Balance: ${balance:,.2f}")
                    return balance
                except:
                    continue

            logger.warning("⚠️ Could not retrieve account balance")
            return None

        except Exception as e:
            logger.error(f"❌ Error getting balance: {e}")
            return None

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get list of open positions"""
        try:
            positions = []

            # Navigate to positions tab if needed
            positions_tab_selectors = [
                (By.XPATH, "//a[contains(text(), 'Positions')]"),
                (By.ID, "positions-tab"),
                (By.CLASS_NAME, "positions-link")
            ]

            for by, selector in positions_tab_selectors:
                try:
                    tab = self.driver.find_element(by, selector)
                    tab.click()
                    time.sleep(2)
                    break
                except:
                    continue

            # Get position rows
            position_rows = self.driver.find_elements(By.CSS_SELECTOR, "tr.position-row")

            for row in position_rows:
                try:
                    position = {
                        'instrument': row.find_element(By.CLASS_NAME, "instrument").text,
                        'side': row.find_element(By.CLASS_NAME, "side").text,
                        'volume': float(row.find_element(By.CLASS_NAME, "volume").text),
                        'entry': float(row.find_element(By.CLASS_NAME, "entry-price").text),
                        'current': float(row.find_element(By.CLASS_NAME, "current-price").text),
                        'profit': float(row.find_element(By.CLASS_NAME, "profit").text)
                    }
                    positions.append(position)
                except Exception as e:
                    logger.debug(f"Error parsing position row: {e}")
                    continue

            logger.info(f"📊 Open positions: {len(positions)}")
            return positions

        except Exception as e:
            logger.error(f"❌ Error getting positions: {e}")
            return []

    def close_position(self, position_id: str = None, instrument: str = None) -> bool:
        """
        Close a specific position

        Args:
            position_id: Position ID to close
            instrument: Or close by instrument name

        Returns:
            bool: True if successful
        """
        try:
            logger.info(f"🔒 Closing position: {position_id or instrument}")

            # Find close button for the position
            if position_id:
                close_btn = self.driver.find_element(
                    By.XPATH,
                    f"//tr[@data-position-id='{position_id}']//button[contains(text(), 'Close')]"
                )
            elif instrument:
                close_btn = self.driver.find_element(
                    By.XPATH,
                    f"//tr[contains(., '{instrument}')]//button[contains(text(), 'Close')]"
                )
            else:
                return False

            close_btn.click()
            time.sleep(1)

            # Confirm if needed
            try:
                confirm_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Confirm')]")
                confirm_btn.click()
                time.sleep(1)
            except:
                pass

            logger.info("✅ Position closed")
            return True

        except Exception as e:
            logger.error(f"❌ Error closing position: {e}")
            return False

    def take_screenshot(self, name: str):
        """Take a screenshot for debugging"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshots/e8markets_{name}_{timestamp}.png"
            os.makedirs("screenshots", exist_ok=True)
            self.driver.save_screenshot(filename)
            logger.debug(f"📸 Screenshot saved: {filename}")
        except Exception as e:
            logger.error(f"Error taking screenshot: {e}")

    def close(self):
        """Close browser and cleanup"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("🔒 Browser closed")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")


def main():
    """Main function for testing"""
    # Initialize automation
    bot = E8MarketsAutomation(headless=False)

    try:
        # Initialize browser
        if not bot.initialize_browser():
            logger.error("Failed to initialize browser")
            return

        # Login
        if not bot.login():
            logger.error("Failed to login")
            return

        # Wait for manual interaction if needed
        input("\n⏸️  Press Enter after you've selected your account...")

        # Get account balance
        balance = bot.get_account_balance()

        # Get open positions
        positions = bot.get_open_positions()

        # Example: Place a test order (COMMENTED OUT FOR SAFETY)
        # bot.place_order(
        #     instrument="EURUSD",
        #     order_type="limit",
        #     side="buy",
        #     volume=0.01,
        #     entry_price=1.0850,
        #     stop_loss=1.0800,
        #     take_profit=1.0900
        # )

        # Keep browser open for inspection
        input("\n⏸️  Press Enter to close browser...")

    except KeyboardInterrupt:
        logger.info("Script interrupted by user")
    finally:
        bot.close()


if __name__ == "__main__":
    main()
