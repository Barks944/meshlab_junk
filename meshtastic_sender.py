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

                # Stop the heartbeat to prevent connection reset errors
                if hasattr(self.interface, 'stopHeartbeat'):
                    try:
                        self.interface.stopHeartbeat()
                        logger.info("Heartbeat stopped to prevent connection issues")
                    except Exception as e:
                        logger.warning(f"Could not stop heartbeat: {str(e)}")
                else:
                    logger.warning("stopHeartbeat method not available")

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

    def send_message(self, channel, message, no_wait=False, retry=True):
        if self.interface is None:
            logger.error("Interface is not connected")
            return False
        try:
            logger.info(f"Sending message: '{message}' to channel {channel}")
            # Send the message
            sent_packet = self.interface.sendText(message, channelIndex=channel)
            if not sent_packet:
                logger.error("Failed to send message: No packet returned")
                return False

            packet_id = sent_packet.id
            logger.info(f"Message sent with packet ID: {packet_id}")

            if no_wait:
                logger.info("Skipping QueueStatus confirmation as requested")
                return True

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
            if retry:
                logger.info("Timeout detected, attempting to reconnect...")
                self.close()
                if self.connect():
                    logger.info("Reconnected, retrying send...")
                    return self.send_message(channel, message, no_wait, retry=False)
                else:
                    logger.error("Failed to reconnect after timeout")
            return False
        except ConnectionResetError as e:
            logger.error(f"Connection reset error: {str(e)}. Attempting to reconnect...")
            if retry:
                self.close()
                if self.connect():
                    logger.info("Reconnected successfully. Retrying send...")
                    return self.send_message(channel, message, no_wait, retry=False)  # Retry once
                else:
                    logger.error("Failed to reconnect")
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
