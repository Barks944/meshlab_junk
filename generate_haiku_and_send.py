import requests
import subprocess
import logging
import argparse
import datetime
import time
import shlex

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

def send_haiku(message, ip, channel):
    try:
        # Call send_channel_message.py
        result = subprocess.run([
            "python", "send_channel_message.py", ip, str(channel), shlex.quote(message)
        ], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Haiku sent successfully")
        else:
            logger.error(f"Failed to send haiku: {result.stderr}")
    except Exception as e:
        logger.error(f"Error sending haiku: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate haiku and send to Meshtastic channel")
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("channel", type=int, help="The channel index to send to (must not be 0)")
    parser.add_argument("--repeat-every", type=int, default=None, help="Repeat the message every X seconds. If not specified, send once.")
    args = parser.parse_args()
    
    # Validate channel
    if args.channel == 0:
        parser.error("Channel 0 is not allowed. Please use a channel index from 1-7.")
    
    if args.repeat_every:
        logger.info(f"Repeating every {args.repeat_every} seconds. Press Ctrl+C to stop.")
        try:
            while True:
                haiku = generate_haiku()
                if haiku:
                    now = datetime.datetime.now()
                    compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
                    full_haiku = f"{compact_dt} {haiku}"
                    send_haiku(full_haiku, args.ip, args.channel)
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
            send_haiku(full_haiku, args.ip, args.channel)
        else:
            logger.error("No haiku generated, skipping send.")
