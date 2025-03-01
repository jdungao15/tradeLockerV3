import requests
import aiohttp
import json
import os
import logging
import asyncio
from dotenv import load_dotenv
from functools import lru_cache

load_dotenv()
logger = logging.getLogger(__name__)

api_key = os.getenv("OPENAI_API_KEY")
api_url = "https://api.openai.com/v1/chat/completions"

# Cache for parsed signals to avoid duplicate processing
parsed_signal_cache = {}


def parse_signal(message: str):
    """
    Parse a trading signal using OpenAI API - synchronous version.
    Caches results to avoid re-parsing identical messages.
    """
    # Check cache first
    if message in parsed_signal_cache:
        logger.info("Using cached parsed signal")
        return parsed_signal_cache[message]

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
        logger.debug(f"Content from signal_parser.py: {content}")

        if content.lower() == "null":
            logger.info("Not a valid trading signal")
            return None

        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing OpenAI response: {e}")
            return None

        # Adjust prices for different brokers
        if result.get("instrument") == "DJI30":
            result["stop_loss"] += 46
            result["entry_point"] += 46
            result["take_profits"] = [tp + 46 for tp in result["take_profits"]]

        # Cache the result
        parsed_signal_cache[message] = result
        return result

    except Exception as e:
        logger.error(f"Error parsing signal: {e}", exc_info=True)
        return None


async def parse_signal_async(message: str):
    """
    Parse a trading signal using OpenAI API - asynchronous version.
    Caches results to avoid re-parsing identical messages.
    """
    # Check cache first
    if message in parsed_signal_cache:
        logger.info("Using cached parsed signal")
        return parsed_signal_cache[message]

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
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

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload) as response:
                response.raise_for_status()
                json_response = await response.json()
                content = json_response["choices"][0]["message"]["content"].strip()

                logger.debug(f"Content from signal_parser.py: {content}")

                if content.lower() == "null":
                    logger.info("Not a valid trading signal")
                    return None

                try:
                    result = json.loads(content)
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing OpenAI response: {e}")
                    return None

                # Adjust prices for different brokers
                if result.get("instrument") == "DJI30":
                    result["stop_loss"] += 46
                    result["entry_point"] += 46
                    result["take_profits"] = [tp + 46 for tp in result["take_profits"]]

                # Cache the result
                parsed_signal_cache[message] = result
                return result

    except Exception as e:
        logger.error(f"Error parsing signal: {e}", exc_info=True)
        return None


# Helper function to extract price points from complex messages
def extract_price_points(text: str):
    """
    Extracts potential price points like entry points, stop loss levels,
    and take profit targets from text.
    Returns a dictionary of identified values.
    """
    import re

    # Patterns to match common price formats
    entry_patterns = [
        r"(?:entry|buy|sell)(?:\s+at)?\s+(?:around|near|at)?\s*:?\s*(\d+\.?\d*)",
        r"(?:entry|buy|sell)(?:\s+around|near)?\s*:?\s*(\d+\.?\d*)",
        r"(?:entry|buy|sell)(?:\s+point)?\s*:?\s*(\d+\.?\d*)"
    ]

    stop_patterns = [
        r"(?:stop|sl|stop\s+loss)(?:\s+at)?\s*:?\s*(\d+\.?\d*)",
        r"(?:stop|sl|stop\s+loss)(?:\s+around|near)?\s*:?\s*(\d+\.?\d*)"
    ]

    target_patterns = [
        r"(?:target|tp|take\s+profit|profit\s+target)\s*:?\s*(\d+\.?\d*)",
        r"(?:target|tp|take\s+profit|profit\s+target)\s+(\d+)\s*:?\s*(\d+\.?\d*)",
        r"(?:targets|tps|take\s+profits)\s*:?\s*(\d+\.?\d*)[,\s]+(\d+\.?\d*)[,\s]+(\d+\.?\d*)"
    ]

    results = {
        "potential_entries": [],
        "potential_stops": [],
        "potential_targets": []
    }

    # Extract entries
    for pattern in entry_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            results["potential_entries"].extend([float(m) for m in matches if m])

    # Extract stops
    for pattern in stop_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            results["potential_stops"].extend([float(m) for m in matches if m])

    # Extract targets - simple cases
    for pattern in target_patterns[:2]:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            for match in matches:
                if isinstance(match, tuple):
                    # Format with target number and value
                    results["potential_targets"].append(float(match[-1]))
                else:
                    # Simple value
                    results["potential_targets"].append(float(match))

    # Extract multiple targets in one line
    for pattern in target_patterns[2:]:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            for match in matches:
                # Add all values from the tuple
                results["potential_targets"].extend([float(m) for m in match if m])

    return results


# Clear signal cache periodically (every 24 hours)
async def cache_maintenance_task():
    """Background task to clear signal cache periodically"""
    while True:
        try:
            await asyncio.sleep(86400)  # 24 hours
            parsed_signal_cache.clear()
            logger.info("Signal parser cache cleared")
        except Exception as e:
            logger.error(f"Error in cache maintenance: {e}")
            await asyncio.sleep(3600)  # Try again in an hour if error occurs


# Start the cache maintenance task
def start_cache_maintenance():
    """Start the cache maintenance background task"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(cache_maintenance_task())
            logger.info("Signal parser cache maintenance task started")
    except RuntimeError:
        # No event loop, probably running in sync context
        pass


# Initialize cache maintenance
start_cache_maintenance()