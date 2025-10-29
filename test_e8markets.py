#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E8 Markets API Testing Script
Test and explore the E8 Markets platform authentication and interface
"""
import os
import time
import json
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Load environment variables
load_dotenv()


class E8MarketsAPITester:
    """Test and explore E8 Markets platform"""

    def __init__(self):
        self.driver = None
        self.email = os.getenv('E8MARKETS_EMAIL', 'johnmiguel.dungao@gmail.com')
        self.password = 'n2S=VA2B'
        self.partner_id = '2'
        self.login_url = f"https://mtr.e8markets.com/match-trader-edge/multi-broker-access/available-brokers/login?partnerId={self.partner_id}&email={self.email}"

    def initialize_browser(self):
        """Initialize Chrome browser"""
        print("🚀 Initializing browser...")

        chrome_options = Options()
        # Run in visible mode to see what's happening
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        })

        print("✅ Browser initialized")

    def navigate_to_login(self):
        """Navigate to login URL"""
        print(f"\n🌐 Navigating to: {self.login_url}")
        self.driver.get(self.login_url)
        time.sleep(3)
        print(f"✅ Current URL: {self.driver.current_url}")
        print(f"📄 Page Title: {self.driver.title}")

    def analyze_page_structure(self):
        """Analyze the page structure to understand the interface"""
        print("\n🔍 Analyzing page structure...")

        try:
            # Get all input fields
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            print(f"\n📝 Found {len(inputs)} input fields:")
            for i, inp in enumerate(inputs):
                inp_type = inp.get_attribute('type')
                inp_name = inp.get_attribute('name')
                inp_id = inp.get_attribute('id')
                inp_placeholder = inp.get_attribute('placeholder')
                print(f"  {i+1}. Type: {inp_type}, Name: {inp_name}, ID: {inp_id}, Placeholder: {inp_placeholder}")

            # Get all buttons
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            print(f"\n🔘 Found {len(buttons)} buttons:")
            for i, btn in enumerate(buttons):
                btn_text = btn.text
                btn_type = btn.get_attribute('type')
                btn_class = btn.get_attribute('class')
                print(f"  {i+1}. Text: '{btn_text}', Type: {btn_type}, Class: {btn_class}")

            # Get all links
            links = self.driver.find_elements(By.TAG_NAME, "a")
            print(f"\n🔗 Found {len(links)} links:")
            for i, link in enumerate(links[:10]):  # Show first 10
                link_text = link.text
                link_href = link.get_attribute('href')
                if link_text or link_href:
                    print(f"  {i+1}. Text: '{link_text}', Href: {link_href}")

            # Check for forms
            forms = self.driver.find_elements(By.TAG_NAME, "form")
            print(f"\n📋 Found {len(forms)} forms")

            # Check for iframes
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            print(f"\n🖼️  Found {len(iframes)} iframes")

        except Exception as e:
            print(f"❌ Error analyzing page: {e}")

    def take_screenshot(self, name="test"):
        """Take a screenshot"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshots/e8_test_{name}_{timestamp}.png"
            os.makedirs("screenshots", exist_ok=True)
            self.driver.save_screenshot(filename)
            print(f"📸 Screenshot saved: {filename}")
        except Exception as e:
            print(f"❌ Error taking screenshot: {e}")

    def get_page_source_info(self):
        """Get information from page source"""
        print("\n📄 Analyzing page source...")

        source = self.driver.page_source

        # Check for common patterns
        patterns = {
            'login': ['login', 'sign in', 'authenticate'],
            'password': ['password', 'passwd', 'pwd'],
            'email': ['email', 'e-mail', 'username'],
            'broker': ['broker', 'account', 'select'],
            'dashboard': ['dashboard', 'trading', 'positions'],
            'api': ['api', 'endpoint', 'rest'],
            'websocket': ['websocket', 'ws://', 'wss://']
        }

        found_patterns = {}
        for key, terms in patterns.items():
            found_patterns[key] = any(term in source.lower() for term in terms)

        print("\n🔎 Pattern Detection:")
        for key, found in found_patterns.items():
            status = "✅" if found else "❌"
            print(f"  {status} {key.capitalize()}: {found}")

    def try_login(self):
        """Attempt to login if password is provided"""
        if not self.password:
            print("\n⚠️  No password provided in .env file")
            print("💡 Set E8MARKETS_PASSWORD in your .env file to test login")
            return

        print(f"\n🔐 Attempting login with email: {self.email}")

        try:
            # Look for password field
            password_field = None
            selectors = [
                (By.ID, "password"),
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.XPATH, "//input[@type='password']")
            ]

            for by, selector in selectors:
                try:
                    password_field = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((by, selector))
                    )
                    print(f"✅ Found password field: {by}={selector}")
                    break
                except:
                    continue

            if not password_field:
                print("❌ No password field found on page")
                print("💡 This might mean:")
                print("   - You're already logged in")
                print("   - The page has a different authentication flow")
                print("   - The URL already includes authentication")
                return

            # Enter password
            password_field.clear()
            password_field.send_keys(self.password)
            print("✅ Password entered")
            time.sleep(1)

            # Find submit button
            submit_button = None
            button_selectors = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Login')]"),
                (By.XPATH, "//button[contains(text(), 'Sign In')]"),
                (By.XPATH, "//button[contains(text(), 'Submit')]")
            ]

            for by, selector in button_selectors:
                try:
                    submit_button = self.driver.find_element(by, selector)
                    print(f"✅ Found submit button: {by}={selector}")
                    break
                except:
                    continue

            if submit_button:
                submit_button.click()
                print("✅ Submit button clicked")
                time.sleep(5)

                print(f"\n📍 After login URL: {self.driver.current_url}")
                print(f"📄 After login title: {self.driver.title}")

                self.take_screenshot("after_login")
            else:
                print("❌ No submit button found")

        except Exception as e:
            print(f"❌ Login error: {e}")

    def check_for_api_endpoints(self):
        """Check network requests for API endpoints"""
        print("\n🌐 Checking for API endpoints...")

        # Execute JavaScript to check for API calls
        try:
            script = """
            let apiCalls = [];
            const originalFetch = window.fetch;
            window.fetch = function(...args) {
                apiCalls.push({url: args[0], method: args[1]?.method || 'GET'});
                return originalFetch.apply(this, args);
            };
            return apiCalls;
            """
            self.driver.execute_script(script)
            print("✅ API interceptor installed")
            print("💡 Any API calls made will now be logged")
        except Exception as e:
            print(f"⚠️  Could not install API interceptor: {e}")

    def interactive_mode(self):
        """Enter interactive mode for manual exploration"""
        print("\n" + "="*60)
        print("🎮 INTERACTIVE MODE")
        print("="*60)
        print("\nThe browser will stay open for you to explore.")
        print("You can:")
        print("  1. Manually interact with the page")
        print("  2. Inspect elements with DevTools (F12)")
        print("  3. Complete the login process")
        print("  4. Explore the platform")
        print("\n📝 Commands:")
        print("  - Type 'screenshot' to take a screenshot")
        print("  - Type 'url' to see current URL")
        print("  - Type 'analyze' to re-analyze page structure")
        print("  - Type 'source' to save page source")
        print("  - Type 'quit' to close browser")
        print("="*60)

        while True:
            try:
                command = input("\n> ").strip().lower()

                if command == 'quit':
                    break
                elif command == 'screenshot':
                    self.take_screenshot("manual")
                elif command == 'url':
                    print(f"📍 Current URL: {self.driver.current_url}")
                    print(f"📄 Page Title: {self.driver.title}")
                elif command == 'analyze':
                    self.analyze_page_structure()
                elif command == 'source':
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"page_source_{timestamp}.html"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(self.driver.page_source)
                    print(f"✅ Page source saved to: {filename}")
                elif command == 'help':
                    print("📝 Available commands: screenshot, url, analyze, source, quit, help")
                elif command:
                    print("❓ Unknown command. Type 'help' for available commands")

            except KeyboardInterrupt:
                print("\n\n👋 Exiting interactive mode...")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    def run_full_test(self):
        """Run complete test suite"""
        try:
            # Initialize browser
            self.initialize_browser()

            # Navigate to login
            self.navigate_to_login()
            self.take_screenshot("initial_page")

            # Analyze page
            self.analyze_page_structure()
            self.get_page_source_info()

            # Check for API endpoints
            self.check_for_api_endpoints()

            # Try login if credentials available
            self.try_login()

            # Enter interactive mode
            self.interactive_mode()

        except Exception as e:
            print(f"\n❌ Test error: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Cleanup
            if self.driver:
                print("\n🔒 Closing browser...")
                self.driver.quit()
                print("✅ Browser closed")

    def close(self):
        """Close browser"""
        if self.driver:
            self.driver.quit()


def main():
    """Main test function"""
    print("="*60)
    print("🧪 E8 Markets API Tester")
    print("="*60)
    print(f"\n📧 Email: {os.getenv('E8MARKETS_EMAIL', 'johnmiguel.dungao@gmail.com')}")
    print(f"🔑 Password: {'*' * len(os.getenv('E8MARKETS_PASSWORD', '')) if os.getenv('E8MARKETS_PASSWORD') else 'Not Set'}")
    print(f"🔢 Partner ID: 2")
    print("\n" + "="*60 + "\n")

    tester = E8MarketsAPITester()
    tester.run_full_test()


if __name__ == "__main__":
    main()
