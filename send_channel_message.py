import meshtastic
import meshtastic.tcp_interface
import time
import logging
import datetime
import argparse
import threading
import queue
from meshtastic_sender import MeshtasticSender

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MESHTASTIC_PORT = 4403  # Default TCP port for Meshtastic
RETRY_COUNT = 3  # Number of retries for connection
RETRY_DELAY = 5  # Seconds to wait between retries
QUEUE_STATUS_TIMEOUT = 10  # Seconds to wait for QueueStatus

def main():
    parser = argparse.ArgumentParser(
        description="Send message to Meshtastic channel",
        epilog="Example: python send_channel_message.py 192.168.86.39 1 'Hello World'"
    )
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("channel", type=int, help="The channel index to send to (must not be 0)")
    parser.add_argument("message", help="The message to send")
    parser.add_argument("--repeat-every", type=int, default=None, help="Repeat the message every X seconds. If not specified, send once.")
    parser.add_argument("--no-wait", action="store_true", help="Skip waiting for QueueStatus confirmation and assume send success if no exception occurs")
    args = parser.parse_args()
    
    # Validate channel
    if args.channel == 0:
        parser.error("Channel 0 is not allowed. Please use a channel index from 1-7.")
    
    sender = MeshtasticSender(args.ip)
    if not sender.connect():
        return

    sequence = 0
    try:
        if args.repeat_every:
            logger.info(f"Repeating message every {args.repeat_every} seconds. Press Ctrl+C to stop.")
            while True:
                # Increment sequence number for this attempt (regardless of success/failure)
                current_sequence = sequence
                sequence = (sequence + 1) % 1000
                
                # Keep trying to send the same message until it succeeds
                while True:
                    now = datetime.datetime.now()
                    compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
                    full_message = f"{compact_dt} #{current_sequence} {args.message}"
                    
                    success = sender.send_message(args.channel, full_message, no_wait=args.no_wait)
                    if success:
                        logger.info(f"Successfully sent message #{current_sequence}")
                        break  # Success - exit retry loop and wait for next message
                    else:
                        logger.warning(f"Failed to send message #{current_sequence}, will retry...")
                        time.sleep(5)  # Wait 5 seconds before retry
                
                logger.info(f"Waiting {args.repeat_every} seconds before sending next message.")
                time.sleep(args.repeat_every)
        else:
            now = datetime.datetime.now()
            compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
            full_message = f"{compact_dt} {args.message}"
            sender.send_message(args.channel, full_message, no_wait=args.no_wait)
    except KeyboardInterrupt:
        logger.info("Script stopped by user.")
    finally:
        sender.close()

if __name__ == "__main__":
    main()
