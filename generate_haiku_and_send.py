import requests
import logging
import argparse
import datetime
import time
from meshtastic_sender import MeshtasticSender

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_haiku():
    try:
        # Get current datetime
        now = datetime.datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Connect to local LMStudio server (assuming default port 1234)
        url = "http://localhost:1234/v1/chat/completions"
        payload = {
            "model": "openai/gpt-oss-20b",  # Adjust if your model has a specific name
            "messages": [
                {"role": "user", "content": f"Current time: {current_time}. Generate a short 5-word haiku about the Forest of Dean. Consider topics like wild boar, ale, caving, coal, iron ore, steam trains, local places like aylburton or lydney, cinderford or coleford. Consider the season."}
            ],
            "temperature": 1.5
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        haiku = response.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"Generated haiku: {haiku}")
        return haiku
    except Exception as e:
        logger.error(f"Failed to generate haiku: {str(e)}")
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
    parser = argparse.ArgumentParser(description="Generate haiku and send to Meshtastic channel")
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("channel", type=int, help="The channel index to send to (must not be 0)")
    parser.add_argument("--repeat-every", type=int, default=None, help="Repeat the message every X seconds. If not specified, send once.")
    args = parser.parse_args()
    
    # Validate channel
    if args.channel == 0:
        parser.error("Channel 0 is not allowed. Please use a channel index from 1-7.")
    
    # Initialize MeshtasticSender
    sender = MeshtasticSender(args.ip)
    if not sender.connect():
        logger.error("Failed to connect to Meshtastic device")
        return
    
    try:
        if args.repeat_every:
            logger.info(f"Repeating every {args.repeat_every} seconds. Press Ctrl+C to stop.")
            sequence = 0
            current_haiku = None
            try:
                while True:
                    # Generate haiku only if we don't have one to retry
                    if current_haiku is None:
                        current_haiku = generate_haiku()
                    
                    if current_haiku:
                        now = datetime.datetime.now()
                        compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
                        full_haiku = f"{compact_dt} #{sequence} {current_haiku}"
                        if send_haiku(sender, args.channel, full_haiku):
                            # Success: clear current_haiku to generate new one next time
                            current_haiku = None
                            sequence = (sequence + 1) % 1000
                        else:
                            logger.warning(f"Failed to send haiku #{sequence} after retries, will retry same haiku")
                    else:
                        logger.error("No haiku generated, skipping send.")
                    time.sleep(args.repeat_every)
            except KeyboardInterrupt:
                logger.info("Script stopped by user.")
        else:
            haiku = generate_haiku()
            if haiku:
                now = datetime.datetime.now()
                compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
                full_haiku = f"{compact_dt} {haiku}"
                send_haiku(sender, args.channel, full_haiku)
            else:
                logger.error("No haiku generated, skipping send.")
    finally:
        sender.close()

if __name__ == "__main__":
    main()
