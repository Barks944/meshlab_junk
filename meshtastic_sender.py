import meshtastic
import meshtastic.tcp_interface
import time
import logging
import datetime
import argparse
import threading
import queue
from typing import Optional, Protocol, Union, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MESHTASTIC_PORT = 4403  # Default TCP port for Meshtastic
RETRY_COUNT = 3  # Number of retries for connection
RETRY_DELAY = 5  # Seconds to wait between retries
QUEUE_STATUS_TIMEOUT = 15  # Seconds to wait for QueueStatus (increased from 10)
CONNECTION_STABILITY_DELAY = 2  # Seconds to wait after connection for stability

class _QueueStatusLike(Protocol):
    mesh_packet_id: Any
    res: Any


class MeshtasticSender:
    def __init__(self, ip: str, connect_timeout: int = 10):
        """Create a sender.

        Args:
            ip: Device IP address.
            connect_timeout: Seconds to wait for a single low-level TCPInterface construction
                before considering the attempt failed. This guards against library calls that
                occasionally block indefinitely when a device is unresponsive.
        """
        self.ip = ip
        self.connect_timeout = max(1, int(connect_timeout))
        self.interface: Optional[meshtastic.tcp_interface.TCPInterface] = None
        self.packet_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.stop_event = threading.Event()
        self.listener_thread: Optional[threading.Thread] = None
        self._closed: bool = False
        self._original_send_heartbeat = None

    def connect(self):
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                logger.info(f"Attempt {attempt}/{RETRY_COUNT}: Connecting to device at {self.ip} (timeout {self.connect_timeout}s)...")

                # Perform potentially blocking construction in a thread so we can impose a timeout
                result: dict[str, object] = {}

                def _build_interface():
                    try:
                        result["interface"] = meshtastic.tcp_interface.TCPInterface(self.ip)
                    except BaseException as e:  # Store exception for handling outside
                        result["error"] = e

                t = threading.Thread(target=_build_interface, daemon=True)
                t.start()
                t.join(self.connect_timeout)

                if t.is_alive():
                    logger.error(f"Connect attempt exceeded timeout of {self.connect_timeout}s; abandoning attempt")
                    # Thread left running (daemon) – allow retry loop to proceed
                    raise TimeoutError(f"Interface creation timed out after {self.connect_timeout}s")

                if "error" in result:
                    err = result["error"]
                    if isinstance(err, BaseException):
                        raise err
                    else:
                        raise RuntimeError("Unknown non-exception error captured during connect")

                self.interface = result.get("interface")  # type: ignore[assignment]
                if self.interface is None:
                    raise RuntimeError("TCPInterface creation returned None")
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
                self._stop_heartbeat_safely()

                # Monkeypatch sendHeartbeat to be no-op after close to avoid late timer callbacks
                if hasattr(self.interface, 'sendHeartbeat') and not self._original_send_heartbeat:
                    self._original_send_heartbeat = getattr(self.interface, 'sendHeartbeat')
                    sender_ref = self
                    def _guarded_send_heartbeat(*a, **kw):  # type: ignore[override]
                        if sender_ref._closed:
                            logger.debug("Heartbeat suppressed post-close")
                            return None
                        try:
                            return sender_ref._original_send_heartbeat(*a, **kw)  # type: ignore[misc]
                        except Exception as e:
                            logger.debug(f"Heartbeat call failed: {e}")
                            return None
                    try:
                        setattr(self.interface, 'sendHeartbeat', _guarded_send_heartbeat)
                        logger.info("sendHeartbeat patched with close guard")
                    except Exception as e:
                        logger.debug(f"Could not patch sendHeartbeat: {e}")
                
                # Wait for connection stability
                logger.info(f"Waiting {CONNECTION_STABILITY_DELAY} seconds for connection stability...")
                time.sleep(CONNECTION_STABILITY_DELAY)

                return True
            except TimeoutError as e:
                logger.error(f"Timeout establishing connection (attempt {attempt}/{RETRY_COUNT}): {str(e)}")
                if attempt < RETRY_COUNT:
                    logger.info(f"Retrying connection in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error("All connection attempts failed due to timeout.")
            except ConnectionAbortedError as e:
                logger.error(f"Connection aborted (attempt {attempt}/{RETRY_COUNT}): {str(e)}")
                if attempt < RETRY_COUNT:
                    logger.info(f"Retrying connection in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error("All connection attempts failed due to connection abortion.")
            except ConnectionResetError as e:
                logger.error(f"Connection reset (attempt {attempt}/{RETRY_COUNT}): {str(e)}")
                if attempt < RETRY_COUNT:
                    logger.info(f"Retrying connection in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error("All connection attempts failed due to connection reset.")
            except OSError as e:
                if hasattr(e, 'winerror') and e.winerror == 10053:
                    logger.error(f"Connection aborted by host (WinError 10053) (attempt {attempt}/{RETRY_COUNT}): {str(e)}")
                    if attempt < RETRY_COUNT:
                        logger.info(f"Retrying connection in {RETRY_DELAY} seconds...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.error("All connection attempts failed due to host aborting connection.")
                else:
                    logger.error(f"OS error (attempt {attempt}/{RETRY_COUNT}): {str(e)}")
                    if attempt < RETRY_COUNT:
                        logger.info(f"Retrying connection in {RETRY_DELAY} seconds...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.error("All connection attempts failed.")
            except Exception as e:
                logger.error(f"Attempt {attempt}/{RETRY_COUNT} failed: {str(e)}")
                if attempt < RETRY_COUNT:
                    logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error("All retry attempts failed.")
        return False

    def _stop_heartbeat_safely(self):
        """Safely stop the heartbeat to prevent connection issues"""
        if self.interface is None:
            return
            
        # Try to stop heartbeat using method if available
        stop_method = getattr(self.interface, 'stopHeartbeat', None)
        if stop_method:
            try:
                stop_method()
                logger.info("Heartbeat stopped to prevent connection issues")
            except Exception as e:
                logger.warning(f"Could not stop heartbeat: {str(e)}")
        else:
            logger.warning("stopHeartbeat method not available")
            
        # Additional heartbeat prevention - try to disable it through localNode
        try:
            local_node = getattr(self.interface, 'localNode', None)
            if local_node:
                # Try to set heartbeat interval to a very large value to effectively disable it
                set_interval_method = getattr(local_node, 'setHeartbeatInterval', None)
                if set_interval_method:
                    set_interval_method(86400)  # 24 hours
                    logger.info("Heartbeat interval set to 24 hours to prevent connection issues")
                elif hasattr(local_node, 'heartbeatInterval'):
                    local_node.heartbeatInterval = 86400
                    logger.info("Heartbeat interval set to 24 hours to prevent connection issues")
        except Exception as e:
            logger.debug(f"Could not modify heartbeat interval: {str(e)}")

    def send_message(self, channel, message, no_wait=False, retry=True):
        if self.interface is None:
            logger.error("Interface is not connected")
            return False
        
        max_send_retries = 2 if retry else 0
        
        for send_attempt in range(max_send_retries + 1):
            # Check connection health before attempting send
            if not self._check_connection_health():
                logger.warning("Connection health check failed, attempting recovery...")
                if not self._attempt_connection_recovery():
                    logger.error("Connection recovery failed")
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

                # Wait for QueueStatus with improved timeout handling
                return self._wait_for_queue_status(packet_id)
                
            except ConnectionAbortedError as e:
                logger.error(f"Connection aborted during send (attempt {send_attempt + 1}): {str(e)}")
                if send_attempt < max_send_retries:
                    logger.info("Attempting to reconnect...")
                    self.close()
                    if self.connect():
                        logger.info("Reconnected, retrying send...")
                        continue
                    else:
                        logger.error("Failed to reconnect after connection abort")
                        return False
                else:
                    logger.error("All send attempts failed due to connection abortion")
                    return False
                    
            except ConnectionResetError as e:
                logger.error(f"Connection reset during send (attempt {send_attempt + 1}): {str(e)}")
                if send_attempt < max_send_retries:
                    logger.info("Attempting to reconnect...")
                    self.close()
                    if self.connect():
                        logger.info("Reconnected, retrying send...")
                        continue
                    else:
                        logger.error("Failed to reconnect after connection reset")
                        return False
                else:
                    logger.error("All send attempts failed due to connection reset")
                    return False
                    
            except OSError as e:
                if hasattr(e, 'winerror') and e.winerror == 10053:
                    logger.error(f"Connection aborted by host during send (attempt {send_attempt + 1}): {str(e)}")
                    if send_attempt < max_send_retries:
                        logger.info("Attempting to reconnect...")
                        self.close()
                        if self.connect():
                            logger.info("Reconnected, retrying send...")
                            continue
                        else:
                            logger.error("Failed to reconnect after host abort")
                            return False
                    else:
                        logger.error("All send attempts failed due to host aborting connection")
                        return False
                else:
                    logger.error(f"OS error during send (attempt {send_attempt + 1}): {str(e)}")
                    return False
                    
            except Exception as e:
                logger.error(f"Error sending message (attempt {send_attempt + 1}): {str(e)}")
                if send_attempt < max_send_retries:
                    logger.info("Retrying send...")
                    continue
                else:
                    logger.error("All send attempts failed")
                    return False
        
        return False

    def _wait_for_queue_status(self, packet_id):
        """Wait for QueueStatus confirmation with improved error handling"""
        start_time = time.time()
        consecutive_timeouts = 0
        max_consecutive_timeouts = 3
        
        while time.time() - start_time < QUEUE_STATUS_TIMEOUT:
            try:
                # Use a shorter timeout to be more responsive
                item = self.packet_queue.get(timeout=0.5)
                if item[0] == 'queueStatus':
                    qs_raw = item[1]
                    try:
                        qs: _QueueStatusLike = qs_raw  # type: ignore[assignment]
                        if getattr(qs, 'mesh_packet_id', None) == packet_id:
                            res_val = getattr(qs, 'res', None)
                            if res_val == 0:  # ERRNO_OK
                                logger.info("Message queued successfully for transmission")
                                return True
                            else:
                                logger.error(f"Message failed to queue: Error code {res_val}")
                                return False
                    except Exception:
                        # If structure unexpected, continue waiting
                        continue
                consecutive_timeouts = 0  # Reset on successful queue operation
                
            except queue.Empty:
                consecutive_timeouts += 1
                if consecutive_timeouts >= max_consecutive_timeouts:
                    logger.warning(f"Multiple consecutive timeouts ({consecutive_timeouts}), connection may be unstable")
                continue
            except Exception as e:
                logger.error(f"Error while waiting for queue status: {str(e)}")
                return False

        logger.error(f"Timeout waiting for QueueStatus after {QUEUE_STATUS_TIMEOUT} seconds")
        return False

    def _check_connection_health(self):
        """Check if the connection is still healthy"""
        if self.interface is None:
            return False
            
        try:
            # Try to access a basic property to check if connection is alive
            if hasattr(self.interface, 'localNode') and self.interface.localNode:
                # If we can access localNode, connection is likely healthy
                return True
            else:
                logger.warning("Connection health check failed: localNode not accessible")
                return False
        except Exception as e:
            logger.warning(f"Connection health check failed: {str(e)}")
            return False

    def _attempt_connection_recovery(self):
        """Attempt to recover a broken connection"""
        logger.info("Attempting connection recovery...")
        
        # Close existing connection
        self.close()
        
        # Try to reconnect
        if self.connect():
            logger.info("Connection recovery successful")
            return True
        else:
            logger.error("Connection recovery failed")
            return False

    def close(self):
        if self.interface:
            self._closed = True
            # Attempt to cancel any heartbeat timers on the interface
            try:
                timer = getattr(self.interface, 'heartbeatTimer', None)
                if timer and hasattr(timer, 'cancel'):
                    timer.cancel()
                    logger.info("Heartbeat timer cancelled")
            except Exception as e:
                logger.debug(f"Could not cancel heartbeat timer: {e}")
            try:
                self.interface.close()
                logger.info("Interface closed")
            except Exception as e:
                logger.error(f"Error closing interface: {str(e)}")
