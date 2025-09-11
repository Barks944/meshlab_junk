import meshtastic
import meshtastic.tcp_interface
import time
import logging
import datetime
import argparse
import threading
import queue
import csv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MESHTASTIC_PORT = 4403  # Default TCP port for Meshtastic
RETRY_COUNT = 3  # Number of retries for connection
RETRY_DELAY = 5  # Seconds to wait between retries

class MeshtasticNodeDisplay:
    def __init__(self, ip):
        self.ip = ip
        self.interface = None

    def connect(self):
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                logger.info(f"Attempt {attempt}/{RETRY_COUNT}: Connecting to device at {self.ip}...")
                self.interface = meshtastic.tcp_interface.TCPInterface(self.ip)
                logger.info("TCP connection established successfully")

                if not hasattr(self.interface, 'localNode') or self.interface.localNode is None:
                    logger.error("Local node is not initialized.")
                    return False

                # Wait a bit for nodes to populate
                logger.info("Waiting for node information to populate...")
                time.sleep(5)

                return True
            except Exception as e:
                logger.error(f"Attempt {attempt}/{RETRY_COUNT} failed: {str(e)}")
                if attempt < RETRY_COUNT:
                    logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error("All retry attempts failed.")
        return False

    def display_nodes(self, csv_path=None):
        if self.interface is None:
            logger.error("Interface is not connected")
            return

        logger.info("Displaying known nodes:")
        print("\n" + "="*80)
        print("Meshtastic Nodes Information")
        print("="*80)

        nodes_data = []
        for node_id, node in (self.interface.nodes or {}).items():
            node_info = {
                'Node ID': node_id,
                'Node Number': node.get('num', ''),
                'Long Name': '',
                'Short Name': '',
                'User ID': '',
                'Last Heard': '',
                'SNR': '',
                'Latitude': '',
                'Longitude': '',
                'Altitude': '',
                'Uptime': ''
            }

            if 'user' in node and node['user']:
                user = node['user']
                node_info['Long Name'] = user.get('longName', '')
                node_info['Short Name'] = user.get('shortName', '')
                node_info['User ID'] = user.get('id', '')

            if 'lastHeard' in node and node['lastHeard']:
                last_heard_dt = datetime.datetime.fromtimestamp(node['lastHeard'])
                node_info['Last Heard'] = last_heard_dt.strftime('%Y-%m-%d %H:%M:%S')

            if 'snr' in node and node['snr'] is not None:
                node_info['SNR'] = str(node['snr'])

            if 'position' in node and node['position']:
                pos = node['position']
                if pos.get('latitudeI'):
                    node_info['Latitude'] = str(pos['latitudeI'] / 1e7)
                if pos.get('longitudeI'):
                    node_info['Longitude'] = str(pos['longitudeI'] / 1e7)
                if pos.get('altitude'):
                    node_info['Altitude'] = str(pos['altitude'])

            if 'deviceMetrics' in node and node['deviceMetrics'] and 'uptimeSeconds' in node['deviceMetrics']:
                uptime = node['deviceMetrics']['uptimeSeconds']
                node_info['Uptime'] = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"

            nodes_data.append(node_info)

            # Print to console
            print(f"\nNode ID: {node_info['Node ID']}")
            print(f"Node Number: {node_info['Node Number'] or 'N/A'}")
            print(f"Long Name: {node_info['Long Name'] or 'N/A'}")
            print(f"Short Name: {node_info['Short Name'] or 'N/A'}")
            print(f"User ID: {node_info['User ID'] or 'N/A'}")
            print(f"Last Heard: {node_info['Last Heard'] or 'N/A'}")
            print(f"Signal Strength (SNR): {node_info['SNR'] or 'N/A'} dB")
            print(f"Location: Lat {node_info['Latitude'] or 'N/A'}, Lon {node_info['Longitude'] or 'N/A'}, Alt {node_info['Altitude'] or 'N/A'} m")
            print(f"Uptime: {node_info['Uptime'] or 'N/A'}")
            print("-" * 40)

        print("="*80)

        # Write to CSV if path provided
        if csv_path:
            try:
                with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = ['Node ID', 'Node Number', 'Long Name', 'Short Name', 'User ID', 'Last Heard', 'SNR', 'Latitude', 'Longitude', 'Altitude', 'Uptime']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(nodes_data)
                logger.info(f"Node information saved to {csv_path}")
            except Exception as e:
                logger.error(f"Failed to write to CSV: {str(e)}")

    def close(self):
        if self.interface:
            try:
                self.interface.close()
                logger.info("Interface closed")
            except Exception as e:
                logger.error(f"Error closing interface: {str(e)}")
