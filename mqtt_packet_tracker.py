#!/usr/bin/env python3
"""
MQTT Packet Tracker with Node Information

This script:
1. Periodically fetches node information from the Meshtastic radio
2. Subscribes to a local MQTT server for packet data
3. Stores node positions and other info
4. For each received packet, determines the original transmission location
   using stored node data

Usage:
    python mqtt_packet_tracker.py --mqtt-host localhost --radio-ip 192.168.86.39

Dependencies:
    pip install meshtastic paho-mqtt
"""

import argparse
import json
import time
import threading
from datetime import datetime
import paho.mqtt.client as mqtt
import meshtastic.tcp_interface

# Global storage for node information
node_info = {}  # node_id -> {position, last_seen, etc.}
packet_history = []  # List of recent packets

def fetch_node_info(radio_ip, interval=300):
    """Periodically fetch node information from the radio"""
    while True:
        try:
            print(f"[{datetime.now()}] Fetching node info from radio...")
            interface = meshtastic.tcp_interface.TCPInterface(radio_ip)
            
            # Get all nodes
            nodes = interface.nodes
            
            if nodes:
                for node_id, node_data in nodes.items():
                    node_info[node_id] = {
                        'short_name': node_data.get('user', {}).get('short_name', ''),
                        'long_name': node_data.get('user', {}).get('long_name', ''),
                        'position': node_data.get('position', {}),
                        'last_seen': datetime.now().isoformat(),
                        'battery_level': node_data.get('deviceMetrics', {}).get('batteryLevel'),
                        'snr': node_data.get('snr'),
                        'rssi': node_data.get('rssi')
                    }
                
                print(f"[{datetime.now()}] Updated info for {len(nodes)} nodes")
            
            # Close interface safely
            try:
                interface.close()
            except Exception as close_e:
                print(f"[{datetime.now()}] Warning: Error closing interface: {close_e}")
            
        except Exception as e:
            print(f"[{datetime.now()}] Error fetching node info: {e}")
        
        time.sleep(interval)

def on_mqtt_connect(client, userdata, flags, rc):
    """Callback when MQTT client connects"""
    print(f"[{datetime.now()}] Connected to MQTT broker with result code {rc}")
    # Subscribe to all meshtastic topics
    client.subscribe("meshtastic/#")

def on_mqtt_message(client, userdata, msg):
    """Callback when MQTT message is received"""
    try:
        # Only process JSON messages, skip binary ones
        if '/json/' in msg.topic:
            payload = msg.payload.decode('utf-8')
            packet_data = json.loads(payload)
            process_packet(packet_data)
        elif '/e/' in msg.topic:
            # Binary protobuf message - skip for now
            # Could decode protobuf if needed in the future
            pass
        else:
            # Try to decode as UTF-8 for other topics
            try:
                payload = msg.payload.decode('utf-8')
                print(f"[{datetime.now()}] Received non-meshtastic message on {msg.topic}: {payload[:100]}...")
            except UnicodeDecodeError:
                print(f"[{datetime.now()}] Received binary message on {msg.topic} (skipping)")
            
    except Exception as e:
        print(f"[{datetime.now()}] Error processing MQTT message: {e}")

def process_packet(packet_data):
    """Process a received packet and determine transmission location"""
    packet_type = packet_data.get('type', 'unknown')
    sender_id = packet_data.get('sender', '')
    from_id = packet_data.get('from', 0)
    from_hex = f"!{from_id:08x}" if from_id else ""
    
    print(f"\n[{datetime.now()}] Received {packet_type} packet from {from_hex}")
    
    # Store packet in history
    packet_history.append({
        'timestamp': datetime.now().isoformat(),
        'data': packet_data
    })
    
    # Keep only recent packets
    if len(packet_history) > 100:
        packet_history.pop(0)
    
    # Update node info if this is a position or nodeinfo packet
    if packet_type == 'position':
        position = packet_data.get('payload', {})
        if from_hex and from_hex in node_info:
            node_info[from_hex]['position'] = position
            node_info[from_hex]['last_seen'] = datetime.now().isoformat()
        elif from_hex:
            node_info[from_hex] = {
                'position': position,
                'last_seen': datetime.now().isoformat()
            }
    
    elif packet_type == 'nodeinfo':
        node_payload = packet_data.get('payload', {})
        node_id = node_payload.get('id', '')
        if node_id:
            node_info[node_id] = {
                'short_name': node_payload.get('shortname', ''),
                'long_name': node_payload.get('longname', ''),
                'last_seen': datetime.now().isoformat()
            }
    
    elif packet_type == 'telemetry':
        telemetry = packet_data.get('payload', {})
        if from_hex and from_hex in node_info:
            node_info[from_hex]['battery_level'] = telemetry.get('battery_level')
            node_info[from_hex]['last_seen'] = datetime.now().isoformat()
    
    # Determine transmission location
    transmission_location = determine_transmission_location(packet_data)
    
    if transmission_location:
        print(f"  Original transmission location: {transmission_location}")
    else:
        print("  Unable to determine transmission location")

def determine_transmission_location(packet_data):
    """Determine where the packet was originally transmitted from"""
    from_id = packet_data.get('from', 0)
    from_hex = f"!{from_id:08x}" if from_id else ""
    
    # Check if we have stored position for this node
    if from_hex in node_info:
        position = node_info[from_hex].get('position', {})
        if position:
            lat = position.get('latitude_i', 0) / 1e7 if 'latitude_i' in position else position.get('latitude', 0)
            lon = position.get('longitude_i', 0) / 1e7 if 'longitude_i' in position else position.get('longitude', 0)
            alt = position.get('altitude', 0)
            
            if lat and lon:
                return f"Lat: {lat:.6f}, Lon: {lon:.6f}, Alt: {alt}m"
    
    # If no stored position, try to estimate based on RSSI/SNR from gateway
    rssi = packet_data.get('rssi')
    snr = packet_data.get('snr')
    
    if rssi is not None:
        # Rough distance estimation (this is approximate and depends on environment)
        # RSSI decreases with distance, but this is very basic
        estimated_distance = estimate_distance_from_rssi(rssi)
        return f"Estimated distance from gateway: ~{estimated_distance:.1f}m (based on RSSI: {rssi}dB)"
    
    return None

def estimate_distance_from_rssi(rssi, tx_power=-20, path_loss_exponent=2.0):
    """Rough distance estimation from RSSI (very approximate)"""
    if rssi >= tx_power:
        return 0.0
    
    # Free space path loss formula (simplified)
    path_loss = tx_power - rssi
    distance = 10 ** ((path_loss - 20 * 2.0) / (10 * path_loss_exponent))
    return distance

def main():
    parser = argparse.ArgumentParser(description='MQTT Packet Tracker with Node Information')
    parser.add_argument('--mqtt-host', default='localhost', help='MQTT broker host')
    parser.add_argument('--mqtt-port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--radio-ip', default='192.168.86.39', help='Meshtastic radio IP address')
    parser.add_argument('--fetch-interval', type=int, default=300, help='Node info fetch interval (seconds)')
    
    args = parser.parse_args()
    
    # Start node info fetching thread
    fetch_thread = threading.Thread(target=fetch_node_info, args=(args.radio_ip, args.fetch_interval))
    fetch_thread.daemon = True
    fetch_thread.start()
    
    # Setup MQTT client
    client = mqtt.Client()
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    
    try:
        client.connect(args.mqtt_host, args.mqtt_port, 60)
        print(f"[{datetime.now()}] Starting MQTT packet tracker...")
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Stopping...")
    except Exception as e:
        print(f"[{datetime.now()}] Error: {e}")

if __name__ == "__main__":
    main()
