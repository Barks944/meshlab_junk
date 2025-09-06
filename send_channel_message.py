import meshtastic
import meshtastic.tcp_interface
import time
import logging
import socket
import datetime
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CHANNEL_INDEX = 1
MESHTASTIC_PORT = 4403  # Default TCP port for Meshtastic
RETRY_COUNT = 3  # Number of retries for connection
RETRY_DELAY = 5  # Seconds to wait between retries

def check_device_connection(ip, port=4403, timeout=5):
    """Check if the device is reachable via TCP port."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            logger.info(f"TCP connection to {ip}:{port} succeeded")
            return True
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        logger.error(f"TCP connection to {ip}:{port} failed: {str(e)}")
        return False

def send_message(ip, message):
    interface = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            # Verify device is reachable
            if not check_device_connection(ip, MESHTASTIC_PORT):
                logger.error(f"Device at {ip} is not reachable. Check network, IP, or device status.")
                return

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
    parser = argparse.ArgumentParser(description="Send message to Meshtastic channel")
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("message", help="The message to send")
    args = parser.parse_args()
    compact_dt = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    full_message = f"{compact_dt} {args.message}"
    send_message(args.ip, full_message)