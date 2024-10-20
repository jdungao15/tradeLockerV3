from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import json
import os


def scrape_economic_events():
    # Specify the path to your ChromeDriver
    chrome_driver_path = 'C:/webDriver/chromedriver.exe'
    service = Service(chrome_driver_path)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")

    driver = webdriver.Chrome(service=service, options=options)
    driver.get("https://www.babypips.com/economic-calendar")

    WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.TAG_NAME, "tbody"))
    )

    rows = driver.find_elements(By.XPATH, "//tbody/tr")
    events = []

    for row in rows:
        try:
            time_text = row.find_element(By.XPATH, ".//td[contains(@class, 'time')]").text.strip()

            if time_text.lower() != "all day":
                time_obj = datetime.strptime(time_text, "%H:%M")
                rounded_minutes = (time_obj.minute // 5) * 5
                time_rounded = time_obj.replace(minute=rounded_minutes).strftime("%I:%M %p EST")
            else:
                time_rounded = "All Day"

            currency = row.find_element(By.XPATH,
                                        ".//td[contains(@class, 'currency')]//div[contains(@class, 'code')]").text.strip()
            event_name = row.find_element(By.XPATH, ".//td[contains(@class, 'name')]/a").text.strip()
            impact = row.find_element(By.XPATH, ".//td[contains(@class, 'impact')]//div").text.lower().strip()

            if impact == "high":
                events.append({
                    "time": time_rounded,
                    "currency": currency,
                    "event_name": event_name,
                    "impact": impact
                })

        except Exception as e:
            print(f"Error parsing row: {e}")

    driver.quit()

    # Save the output JSON inside economic_api folder
    output_file = "economic_api/economic_events.json"

    # Remove the existing file to ensure it doesn't accumulate old data
    if os.path.exists(output_file):
        print(f"Deleting old {output_file}")
        os.remove(output_file)

    # Save the new scraped data
    with open(output_file, 'w') as json_file:
        json.dump(events, json_file, indent=4)

    print(f"Scraped data saved to {output_file}")


def ensure_economic_data_exists():
    """
    Check if the economic_events.json file exists. If it doesn't, scrape the data.
    """
    output_file = "economic_api/economic_events.json"

    if not os.path.exists(output_file):
        print(f"{output_file} does not exist. Scraping data...")
        scrape_economic_events()
    else:
        print(f"{output_file} already exists. No need to scrape.")
