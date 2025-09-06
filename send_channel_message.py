import meshtastic
import meshtastic.tcp_interface
import time
import logging
import datetime
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CHANNEL_INDEX = 1
MESHTASTIC_PORT = 4403  # Default TCP port for Meshtastic
RETRY_COUNT = 3  # Number of retries for connection
RETRY_DELAY = 5  # Seconds to wait between retries

def send_message(ip, message):
    interface = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            # Connect to the device via TCP
            logger.info(f"Attempt {attempt}/{RETRY_COUNT}: Connecting to device at {ip}...")
            interface = meshtastic.tcp_interface.TCPInterface(ip)
            logger.info("TCP connection established successfully")

            # Check if localNode is available
            if not hasattr(interface, 'localNode') or interface.localNode is None:
                logger.error("Local node is not initialized. Check firmware or library compatibility.")
                return

            # Send message to the specified channel
            logger.info(f"Sending message: '{message}' to channel {CHANNEL_INDEX}")
            interface.sendText(message, channelIndex=CHANNEL_INDEX)
            logger.info("Message sent successfully")
            break  # Exit retry loop on success

        except Exception as e:
            logger.error(f"Attempt {attempt}/{RETRY_COUNT} failed: {str(e)}")
            if attempt < RETRY_COUNT:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error("All retry attempts failed. Check device, firmware, and library compatibility.")
        finally:
            if interface:
                try:
                    interface.close()
                    logger.info("Interface closed")
                except Exception as e:
                    logger.error(f"Error closing interface: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Send message to Meshtastic channel",
        epilog="Example: python send_channel_message.py 192.168.86.39 'Hello World'"
    )
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("message", help="The message to send")
    args = parser.parse_args()
    now = datetime.datetime.now()
    compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
    full_message = f"{compact_dt} {args.message}"
    send_message(args.ip, full_message)