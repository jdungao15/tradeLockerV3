import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("API_KEY")
api_url = os.getenv("API_URL")

def parse_signal(message: str):
    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a trading signal parser. Always respond with a valid JSON object and nothing else."
                    },
                    {
                        "role": "user",
                        "content": f'''Parse the following trading signal and return a JSON object:

                        "{message}"

                        Rules:
                        1. The JSON object should have these fields: instrument, order_type, entry_point, stop_loss, and take_profits.
                        1.1 orderType should only return 'buy' or 'sell'.
                        2. If the entry point is a range, use the first value.
                        3. If the stop loss is a range, use the first value.
                        4. take_profits should always be an array, even if there's only one value.
                        4.1 Only takes the first 3 take profits.
                        4.2 if its index like DJI30, US30 NDX100 or NAS100 take all profits
                        5. Convert instrument names as follows:
                           - US30 to DJI30
                           - NAS100 to NDX100
                           - GOLD to XAUUSD
                           - SILVER to XAGUSD
                        6. Ensure all numeric values are numbers, not strings.
                        7. Make sure that the fields are in the correct format and order and cannot be null or empty.
                        8. If the input is not a valid trading signal, return null.
                        9.Naming convention should be snake case like in python.
                    

                        Respond only with the JSON object or null, no additional text.'''
                    }
                ]
            }
        )

        content = response.json()["choices"][0]["message"]["content"].strip()
        print(f"Content from signal_paser.py {content}")

        if content.lower() == "null":
            print("Not a valid trading signal")
            return None

        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            print("Error parsing OpenAI response:", e)
            return None



        #Change the value of initial prices for different brokers.
        if result["instrument"] == "DJI30":
            result["stop_loss"] += 46
            result["entry_point"] += 46
            result["take_profits"] = [tp + 46 for tp in result["take_profits"]]
        print(f"Result from signal_parser.py {result}")
        return result

    except Exception as e:
        print("Error parsing signal:", e)
        return None
