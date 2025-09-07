import meshtastic
import meshtastic.tcp_interface
import time
import logging
import datetime
import argparse
import threading
import queue

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MESHTASTIC_PORT = 4403  # Default TCP port for Meshtastic
RETRY_COUNT = 3  # Number of retries for connection
RETRY_DELAY = 5  # Seconds to wait between retries
QUEUE_STATUS_TIMEOUT = 10  # Seconds to wait for QueueStatus

class MeshtasticSender:
    def __init__(self, ip):
        self.ip = ip
        self.interface = None
        self.packet_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.listener_thread = None

    def connect(self):
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                logger.info(f"Attempt {attempt}/{RETRY_COUNT}: Connecting to device at {self.ip}...")
                self.interface = meshtastic.tcp_interface.TCPInterface(self.ip)
                logger.info("TCP connection established successfully")

                if not hasattr(self.interface, 'localNode') or self.interface.localNode is None:
                    logger.error("Local node is not initialized.")
                    return False

                # Set up packet handler to receive QueueStatus
                original_packet_handler = self.interface._handlePacketFromRadio
                original_from_radio_handler = self.interface._handleFromRadio
                
                def packet_handler(meshPacket, hack=False):
                    try:
                        self.packet_queue.put(('packet', meshPacket))
                        return original_packet_handler(meshPacket, hack)
                    except Exception as e:
                        logger.error(f"Error in packet handler: {str(e)}")
                        return None
                
                def from_radio_handler(fromRadioBytes):
                    try:
                        # Try to decode the FromRadio message
                        from meshtastic.protobuf import mesh_pb2
                        from_radio = mesh_pb2.FromRadio()
                        from_radio.ParseFromString(fromRadioBytes)
                        
                        if from_radio.HasField('queueStatus'):
                            self.packet_queue.put(('queueStatus', from_radio.queueStatus))
                        
                        return original_from_radio_handler(fromRadioBytes)
                    except Exception as e:
                        logger.error(f"Error in from_radio handler: {str(e)}")
                        return original_from_radio_handler(fromRadioBytes)
                
                self.interface._handlePacketFromRadio = packet_handler
                self.interface._handleFromRadio = from_radio_handler

                return True
            except Exception as e:
                logger.error(f"Attempt {attempt}/{RETRY_COUNT} failed: {str(e)}")
                if attempt < RETRY_COUNT:
                    logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error("All retry attempts failed.")
        return False

    def _listen_for_packets(self):
        # This method is no longer needed as we use handlers
        pass

    def send_message(self, channel, message):
        try:
            logger.info(f"Sending message: '{message}' to channel {channel}")
            # Send the message
            sent_packet = self.interface.sendText(message, channelIndex=channel)
            if not sent_packet:
                logger.error("Failed to send message: No packet returned")
                return False

            packet_id = sent_packet.id
            logger.info(f"Message sent with packet ID: {packet_id}")

            # Wait for QueueStatus
            start_time = time.time()
            while time.time() - start_time < QUEUE_STATUS_TIMEOUT:
                try:
                    item = self.packet_queue.get(timeout=1)
                    if item[0] == 'queueStatus':
                        qs = item[1]
                        if qs.mesh_packet_id == packet_id:
                            if qs.res == 0:  # ERRNO_OK
                                logger.info("Message queued successfully for transmission")
                                return True
                            else:
                                logger.error(f"Message failed to queue: Error code {qs.res}")
                                return False
                except queue.Empty:
                    continue

            logger.error("Timeout waiting for QueueStatus")
            return False
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return False

    def close(self):
        if self.interface:
            try:
                self.interface.close()
                logger.info("Interface closed")
            except Exception as e:
                logger.error(f"Error closing interface: {str(e)}")

def main():
    parser = argparse.ArgumentParser(
        description="Send message to Meshtastic channel",
        epilog="Example: python send_channel_message.py 192.168.86.39 1 'Hello World'"
    )
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("channel", type=int, help="The channel index to send to (must not be 0)")
    parser.add_argument("message", help="The message to send")
    parser.add_argument("--repeat-every", type=int, default=None, help="Repeat the message every X seconds. If not specified, send once.")
    args = parser.parse_args()
    
    # Validate channel
    if args.channel == 0:
        parser.error("Channel 0 is not allowed. Please use a channel index from 1-7.")
    
    sender = MeshtasticSender(args.ip)
    if not sender.connect():
        return

    try:
        if args.repeat_every:
            logger.info(f"Repeating message every {args.repeat_every} seconds. Press Ctrl+C to stop.")
            while True:
                now = datetime.datetime.now()
                compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
                full_message = f"{compact_dt} {args.message}"
                success = sender.send_message(args.channel, full_message)
                if not success:
                    logger.warning("Send failed, but continuing repeat...")
                logger.info(f"Waiting {args.repeat_every} seconds before sending next message.")
                time.sleep(args.repeat_every)
        else:
            now = datetime.datetime.now()
            compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
            full_message = f"{compact_dt} {args.message}"
            sender.send_message(args.channel, full_message)
    except KeyboardInterrupt:
        logger.info("Script stopped by user.")
    finally:
        sender.close()

if __name__ == "__main__":
    main()
