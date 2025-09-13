import requests
import logging
import argparse
import datetime
import time
import json
import os
from typing import Optional
from meshtastic_sender import MeshtasticSender

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global list to store recent haikus
recent_haikus = []
HAIKU_HISTORY_FILE = "haiku_history.json"
LLM_LOG_FILE = "llm_messages.log"

def log_llm_messages(system_message, user_message, timestamp):
    """Log the messages sent to the LLM to a file (overwrites each time)"""
    try:
        with open(LLM_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"=== LLM Request Log ===\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"\n--- System Message ---\n")
            f.write(system_message)
            f.write(f"\n\n--- User Message ---\n")
            f.write(user_message)
            f.write(f"\n\n--- Recent Haiku History ---\n")
            if recent_haikus:
                for i, haiku in enumerate(recent_haikus[-5:], 1):  # Show last 5
                    f.write(f"{i}. {haiku}\n")
            else:
                f.write("No recent haiku history\n")
            f.write(f"\n{'='*50}\n")
        logger.debug(f"LLM messages logged to {LLM_LOG_FILE}")
    except Exception as e:
        logger.error(f"Failed to log LLM messages: {e}")

def load_haiku_history():
    """Load recent haiku history from file"""
    global recent_haikus
    try:
        if os.path.exists(HAIKU_HISTORY_FILE):
            with open(HAIKU_HISTORY_FILE, 'r', encoding='utf-8') as f:
                recent_haikus = json.load(f)
                logger.info(f"Loaded {len(recent_haikus)} haikus from history")
        else:
            recent_haikus = []
            logger.info("No haiku history file found, starting fresh")
    except Exception as e:
        logger.warning(f"Failed to load haiku history: {e}")
        recent_haikus = []

def save_haiku_history():
    """Save recent haiku history to file"""
    try:
        with open(HAIKU_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(recent_haikus, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save haiku history: {e}")

def add_haiku_to_history(haiku):
    """Add a haiku to the recent history"""
    global recent_haikus
    if haiku and haiku not in recent_haikus:
        recent_haikus.append(haiku)
        # Keep only the last 20 haikus
        if len(recent_haikus) > 20:
            recent_haikus = recent_haikus[-20:]
        save_haiku_history()
        logger.debug(f"Added haiku to history: {haiku}")

def validate_and_clean_haiku(haiku):
    """Validate and clean haiku to ensure only allowed special characters remain"""
    if not haiku:
        return "Silent forest whispers"
    
    # Define allowed special characters
    allowed_chars = {'.', ',', ';'}
    
    # Remove any characters that are not letters, numbers, spaces, or allowed special chars
    cleaned = []
    for char in haiku:
        if char.isalnum() or char.isspace() or char in allowed_chars:
            cleaned.append(char)
        # Replace other special characters with appropriate alternatives
        elif char in {'!', '?', ':', '-', '—', '–', '…', '(', ')', '[', ']', '{', '}', '"', "'", '“', '”', '‘', '’'}:
            # Replace punctuation with period or comma where appropriate
            if char in {'!', '?', ':'}:
                cleaned.append('.')
            elif char in {'-', '—', '–'}:
                cleaned.append(',')
            # Skip other punctuation marks
        else:
            # Replace any other special characters with space
            cleaned.append(' ')
    
    # Join and clean up extra spaces
    result = ''.join(cleaned)
    result = ' '.join(result.split())  # Remove extra spaces
    
    # Ensure we have some content
    if not result.strip():
        return "Silent forest whispers"
    
    return result.strip()

def generate_haiku(llm_timeout: int = 25, llm_retries: int = 2) -> Optional[str]:
    """Generate a haiku using local LLM with timeout and retries.

    Args:
        llm_timeout: Total request timeout (seconds). Applied to both connect/read via tuple.
        llm_retries: Number of additional retries (beyond first attempt) on transient failures.
    """
    logger.info("Starting haiku generation...")
    # Clamp parameters
    llm_timeout = max(5, llm_timeout)
    llm_retries = max(0, min(llm_retries, 5))

    # Prepare static prompt parts once
    now = datetime.datetime.now()
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")
    system_message = (
        "You are a creative poet specializing in haiku about the Forest of Dean. "
        "Create original, unique haiku that capture the essence of this beautiful forest area.\n"
        "Use ONLY these special characters: periods (.), commas (,), semicolons (;).\n"
        "Do NOT use exclamation marks, question marks, colons, dashes, quotes, parentheses, or any other special characters.\n"
        "Keep haiku to 5-7 words maximum.\n"
        "Focus on themes like: wild boar, ale, caving, coal, iron ore, steam trains, local places (Aylburton, Lydney, Cinderford, Coleford), seasonal changes, nature, history."
    )

    user_message = f"Current time: {current_time}. Generate a short 5-word haiku about the Forest of Dean."
    if recent_haikus:
        user_message += "\n\nRecent haiku history (avoid repeating these themes or phrases):"
        for i, old_haiku in enumerate(recent_haikus[-5:], 1):
            user_message += f"\n{i}. {old_haiku}"
    user_message += (
        "\n\nConsider topics like wild boar, ale, caving, coal, iron ore, steam trains, "
        "local places like aylburton or lydney, cinderford or coleford. Consider the season."
    )

    log_llm_messages(system_message, user_message, current_time)

    url = "http://localhost:1234/v1/chat/completions"
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "temperature": 1.5,
    }

    attempt = 0
    backoff = 3
    while attempt <= llm_retries:
        attempt += 1
        try:
            logger.info(f"LLM request attempt {attempt}/{llm_retries + 1} (timeout {llm_timeout}s)")
            response = requests.post(
                url,
                json=payload,
                timeout=(min(5, llm_timeout // 2), llm_timeout),  # (connect, read)
            )
            response.raise_for_status()
            data = response.json()
            haiku_raw = data["choices"][0]["message"]["content"].strip()
            original_haiku = haiku_raw
            haiku_clean = validate_and_clean_haiku(haiku_raw)
            if haiku_clean != original_haiku:
                logger.info(f"Cleaned haiku: '{original_haiku}' -> '{haiku_clean}'")
            if haiku_clean and haiku_clean != "Silent forest whispers":
                add_haiku_to_history(haiku_clean)
            logger.info(f"Generated haiku: {haiku_clean}")
            return haiku_clean
        except (requests.Timeout, requests.ConnectionError) as e:
            logger.warning(f"Transient LLM error: {e}")
            if attempt <= llm_retries:
                logger.info(f"Retrying LLM request in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            else:
                break
        except Exception as e:
            logger.error(f"Failed to generate haiku (non-retryable): {e}")
            break

    logger.error("All LLM attempts failed; returning fallback haiku")
    return None

def send_haiku(sender, channel, message):
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Sending haiku (attempt {attempt}/{max_retries}): {message[:50]}...")
            # Send directly using MeshtasticSender
            if sender.send_message(channel, message):
                logger.info("Haiku sent successfully")
                return True
            else:
                logger.warning(f"Failed to send haiku (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to send haiku after {max_retries} attempts")
                    return False
                    
        except Exception as e:
            logger.error(f"Error sending haiku (attempt {attempt}/{max_retries}): {str(e)}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to send haiku after {max_retries} attempts")
                return False
    
    return False

def main():
    # Load haiku history at startup
    load_haiku_history()
    
    parser = argparse.ArgumentParser(description="Generate haiku and send to Meshtastic channel")
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("channel", type=int, help="The channel index to send to (must not be 0)")
    parser.add_argument("--repeat-every", type=int, default=None, help="Repeat the message every X seconds. If not specified, send once.")
    parser.add_argument("--llm-timeout", type=int, default=25, help="Timeout in seconds for the LLM request (default 25)")
    parser.add_argument("--llm-retries", type=int, default=2, help="Number of retries for the LLM request on timeout/connection errors (default 2)")
    parser.add_argument("--connect-timeout", type=int, default=10, help="Timeout in seconds for a single Meshtastic connection attempt (default 10)")
    args = parser.parse_args()
    
    # Validate channel
    if args.channel == 0:
        parser.error("Channel 0 is not allowed. Please use a channel index from 1-7.")
    
    if args.repeat_every:
        logger.info(f"Repeating every {args.repeat_every} seconds. Press Ctrl+C to stop.")
        sequence = 0
        try:
            while True:
                # Increment sequence number for this attempt (regardless of success/failure)
                current_sequence = sequence
                sequence = (sequence + 1) % 1000
                
                # Generate haiku before opening connection
                haiku = generate_haiku(args.llm_timeout, args.llm_retries)
                if haiku:
                    now = datetime.datetime.now()
                    compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
                    full_haiku = f"{compact_dt} #{current_sequence} {haiku}"
                    
                    # Open connection, send, then close
                    sender = MeshtasticSender(args.ip, connect_timeout=args.connect_timeout)
                    if sender.connect():
                        try:
                            if send_haiku(sender, args.channel, full_haiku):
                                logger.info(f"Successfully sent haiku #{current_sequence}")
                            else:
                                logger.warning(f"Failed to send haiku #{current_sequence} after retries")
                        finally:
                            sender.close()
                    else:
                        logger.error(f"Failed to connect to Meshtastic device for haiku #{current_sequence}")
                else:
                    logger.error(f"No haiku generated for attempt #{current_sequence}, skipping send.")
                
                time.sleep(args.repeat_every)
        except KeyboardInterrupt:
            logger.info("Script stopped by user.")
    else:
        # Single message: generate haiku first, then connect and send
        haiku = generate_haiku(args.llm_timeout, args.llm_retries)
        if haiku:
            now = datetime.datetime.now()
            compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
            full_haiku = f"{compact_dt} {haiku}"
            
            # Open connection, send, then close
            sender = MeshtasticSender(args.ip, connect_timeout=args.connect_timeout)
            if sender.connect():
                try:
                    send_haiku(sender, args.channel, full_haiku)
                finally:
                    sender.close()
            else:
                logger.error("Failed to connect to Meshtastic device")
        else:
            logger.error("No haiku generated, skipping send.")

if __name__ == "__main__":
    main()
