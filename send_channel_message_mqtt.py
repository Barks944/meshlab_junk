#!/usr/bin/env python3
"""
MQTT Version of Meshtastic Channel Message Sender

This script sends messages to Meshtastic channels via MQTT instead of direct TCP connection.
It publishes messages to the appropriate MQTT topics that Meshtastic devices subscribe to.

Usage:
    python send_channel_message_mqtt.py --channel 1 --message "Hello World" [--repeat-every 300]

Dependencies:
    pip install paho-mqtt
"""

import argparse
import time
import logging
import datetime
import paho.mqtt.client as mqtt
from paho.mqtt import properties

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MQTTMeshtasticSender:
    def __init__(self, mqtt_host='localhost', mqtt_port=1883, client_id=None):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.client_id = client_id or f"meshtastic_sender_{int(time.time())}"
        self.client = None
        self.connected = False

    def on_connect(self, client, userdata, flags, rc):
        """Callback when MQTT client connects"""
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
        else:
            logger.error(f"Failed to connect to MQTT broker: {rc}")
            self.connected = False

    def on_disconnect(self, client, userdata, rc):
        """Callback when MQTT client disconnects"""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection from MQTT broker: {rc}")

    def on_publish(self, client, userdata, mid):
        """Callback when message is published"""
        logger.debug(f"Message published with mid: {mid}")

    def connect(self):
        """Connect to MQTT broker"""
        try:
            self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_publish = self.on_publish

            logger.info(f"Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}...")
            self.client.connect(self.mqtt_host, self.mqtt_port, 60)

            # Start the network loop in a separate thread
            self.client.loop_start()

            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.connected and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            if not self.connected:
                logger.error("Failed to connect to MQTT broker within timeout")
                return False

            return True

        except Exception as e:
            logger.error(f"Error connecting to MQTT broker: {e}")
            return False

    def send_channel_message(self, channel_index, message, qos=1):
        """
        Send a message to a Meshtastic channel via MQTT

        Args:
            channel_index (int): Channel index (1-7, not 0)
            message (str): Message to send
            qos (int): MQTT QoS level (0, 1, or 2)

        Returns:
            bool: True if message was published successfully
        """
        if not self.connected or self.client is None:
            logger.error("Not connected to MQTT broker")
            return False

        try:
            # Format the MQTT topic for channel messages
            # Meshtastic MQTT topics typically use: meshtastic/to/channel/{channel_index}
            topic = f"meshtastic/to/channel/{channel_index}"

            # Publish the message
            result = self.client.publish(topic, message, qos=qos, retain=False)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Published message to topic '{topic}': {message}")
                return True
            else:
                logger.error(f"Failed to publish message: {result.rc}")
                return False

        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def send_node_message(self, node_id, message, qos=1):
        """
        Send a message to a specific Meshtastic node via MQTT

        Args:
            node_id (str): Target node ID (e.g., "!12345678")
            message (str): Message to send
            qos (int): MQTT QoS level (0, 1, or 2)

        Returns:
            bool: True if message was published successfully
        """
        if not self.connected or self.client is None:
            logger.error("Not connected to MQTT broker")
            return False

        try:
            # Format the MQTT topic for direct node messages
            # Meshtastic MQTT topics typically use: meshtastic/to/{node_id}
            topic = f"meshtastic/to/{node_id}"

            # Publish the message
            result = self.client.publish(topic, message, qos=qos, retain=False)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Published message to topic '{topic}': {message}")
                return True
            else:
                logger.error(f"Failed to publish message: {result.rc}")
                return False

        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def close(self):
        """Close the MQTT connection"""
        if self.client and self.connected:
            logger.info("Disconnecting from MQTT broker...")
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
        self.connected = False


def main():
    parser = argparse.ArgumentParser(
        description="Send message to Meshtastic channel via MQTT",
        epilog="Example: python send_channel_message_mqtt.py --channel 1 --message 'Hello World' --repeat-every 300"
    )

    # MQTT connection options
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host (default: localhost)")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port (default: 1883)")
    parser.add_argument("--client-id", help="MQTT client ID (default: auto-generated)")

    # Message options
    parser.add_argument("--channel", type=int, help="Channel index to send to (1-7, cannot be 0)")
    parser.add_argument("--node-id", help="Target node ID to send to (e.g., !12345678). If specified, --channel is ignored")
    parser.add_argument("--message", required=True, help="The message to send")
    parser.add_argument("--repeat-every", type=int, help="Repeat the message every X seconds. If not specified, send once")
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=1, help="MQTT QoS level (default: 1)")

    args = parser.parse_args()

    # Validate arguments
    if not args.channel and not args.node_id:
        parser.error("Either --channel or --node-id must be specified")

    if args.channel and args.node_id:
        parser.error("Cannot specify both --channel and --node-id. Choose one.")

    if args.channel and args.channel == 0:
        parser.error("Channel 0 is not allowed. Please use a channel index from 1-7.")

    if args.channel and (args.channel < 1 or args.channel > 7):
        parser.error("Channel index must be between 1 and 7.")

    # Create MQTT sender
    sender = MQTTMeshtasticSender(
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        client_id=args.client_id
    )

    # Connect to MQTT broker
    if not sender.connect():
        logger.error("Failed to connect to MQTT broker. Exiting.")
        return

    sequence = 0
    try:
        if args.repeat_every:
            logger.info(f"Repeating message every {args.repeat_every} seconds. Press Ctrl+C to stop.")
            while True:
                # Increment sequence number for this attempt
                current_sequence = sequence
                sequence = (sequence + 1) % 1000

                # Format message with timestamp and sequence
                now = datetime.datetime.now()
                compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
                full_message = f"{compact_dt} #{current_sequence} {args.message}"

                # Send message
                if args.node_id:
                    success = sender.send_node_message(args.node_id, full_message, args.qos)
                else:
                    success = sender.send_channel_message(args.channel, full_message, args.qos)

                if success:
                    logger.info(f"Successfully sent message #{current_sequence}")
                else:
                    logger.warning(f"Failed to send message #{current_sequence}")

                logger.info(f"Waiting {args.repeat_every} seconds before sending next message.")
                time.sleep(args.repeat_every)

        else:
            # Send single message
            now = datetime.datetime.now()
            compact_dt = f"{now.month}/{now.day}/{now.year % 100}@{now.hour:02d}{now.minute:02d}"
            full_message = f"{compact_dt} {args.message}"

            if args.node_id:
                success = sender.send_node_message(args.node_id, full_message, args.qos)
            else:
                success = sender.send_channel_message(args.channel, full_message, args.qos)

            if success:
                logger.info("Message sent successfully")
            else:
                logger.error("Failed to send message")

    except KeyboardInterrupt:
        logger.info("Script stopped by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        sender.close()


if __name__ == "__main__":
    main()
