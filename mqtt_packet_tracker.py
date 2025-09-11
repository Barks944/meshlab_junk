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
from paho.mqtt import properties

# Global storage for node information
node_info = {}  # node_id -> {position, last_seen, etc.}
packet_history = []  # List of recent packets
signal_stats = {}  # node_id -> {'rssi': [], 'snr': [], 'is_local': bool}

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
                    user_obj = node_data.get('user', {})
                    # Try different field name variations for names
                    short_name = (user_obj.get('short_name') or 
                                user_obj.get('shortName') or 
                                user_obj.get('shortname') or '')
                    long_name = (user_obj.get('long_name') or 
                               user_obj.get('longName') or 
                               user_obj.get('longname') or '')
                    
                    node_info[node_id] = {
                        'short_name': short_name,
                        'long_name': long_name,
                        'position': node_data.get('position', {}),
                        'last_seen': datetime.now().isoformat(),
                        'battery_level': node_data.get('deviceMetrics', {}).get('batteryLevel'),
                        'snr': node_data.get('snr'),
                        'rssi': node_data.get('rssi')
                    }
                    
                    # Initialize signal stats if not already present
                    if node_id not in signal_stats:
                        signal_stats[node_id] = {'rssi': [], 'snr': [], 'is_local': False}
                        
                    # Update with current readings if available
                    current_rssi = node_data.get('rssi')
                    current_snr = node_data.get('snr')
                    if current_rssi is not None or current_snr is not None:
                        update_signal_stats(node_id, current_rssi, current_snr)
                
                print(f"[{datetime.now()}] Updated info for {len(nodes)} nodes")
                # Debug: show some node info
                sample_nodes = list(nodes.keys())[:3]  # Show first 3 nodes
                for node_id in sample_nodes:
                    node_data = nodes[node_id]
                    user_obj = node_data.get('user', {})
                    print(f"  Debug: Radio node {node_id} -> user keys: {list(user_obj.keys()) if user_obj else 'None'}")
                    print(f"  Debug: Radio node {node_id} -> full user: {user_obj}")
                    short_name = user_obj.get('short_name', '') if 'short_name' in user_obj else user_obj.get('shortName', '')
                    long_name = user_obj.get('long_name', '') if 'long_name' in user_obj else user_obj.get('longName', '')
                    print(f"  Debug: Radio node {node_id} -> short_name: '{short_name}', long_name: '{long_name}'")
            
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
    
    # Track signal strength for the sender
    rssi = packet_data.get('rssi')
    snr = packet_data.get('snr')
    if sender_id:
        update_signal_stats(sender_id, rssi, snr)
    
    # Get node name if available
    node_name = ""
    if from_hex in node_info:
        short_name = node_info[from_hex].get('short_name', '')
        long_name = node_info[from_hex].get('long_name', '')
        print(f"  Debug: Packet from {from_hex} - found in node_info, short_name: '{short_name}', long_name: '{long_name}'")
        if short_name:
            node_name = f" ({short_name}"
            if long_name and long_name != short_name:
                node_name += f" - {long_name}"
            node_name += ")"
        else:
            # Debug: show if we have node info but no name
            print(f"  Debug: Node {from_hex} found in node_info but no short_name (long_name: '{long_name}')")
    else:
        # Debug: show if node not found
        print(f"  Debug: Node {from_hex} not found in node_info (total nodes: {len(node_info)})")
        print(f"  Debug: Available node IDs: {list(node_info.keys())[:5]}...")  # Show first 5 for debugging
    
    print(f"\n[{datetime.now()}] Received {packet_type} packet from {from_hex}{node_name}")
    
    # Show signal strength info
    if rssi is not None or snr is not None:
        signal_info = []
        if rssi is not None:
            signal_info.append(f"RSSI: {rssi}dB")
        if snr is not None:
            signal_info.append(f"SNR: {snr}dB")
        if signal_info:
            print(f"  Signal: {', '.join(signal_info)}")
    
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
            # Try different field name variations for names
            short_name = (node_payload.get('shortname') or 
                        node_payload.get('shortName') or 
                        node_payload.get('short_name') or '')
            long_name = (node_payload.get('longname') or 
                       node_payload.get('longName') or 
                       node_payload.get('long_name') or '')
            
            print(f"  Debug: Updating node_info for {node_id} with shortname: '{short_name}', longname: '{long_name}'")
            node_info[node_id] = {
                'short_name': short_name,
                'long_name': long_name,
                'last_seen': datetime.now().isoformat()
            }
    
    elif packet_type == 'telemetry':
        telemetry = packet_data.get('payload', {})
        if from_hex and from_hex in node_info:
            node_info[from_hex]['battery_level'] = telemetry.get('battery_level')
            node_info[from_hex]['last_seen'] = datetime.now().isoformat()
    
    # Display local nodes information periodically
    if len(packet_history) % 10 == 0:  # Every 10 packets
        display_local_nodes()
    
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

def update_signal_stats(node_id, rssi, snr):
    """Update signal strength statistics for a node"""
    if node_id not in signal_stats:
        signal_stats[node_id] = {'rssi': [], 'snr': [], 'is_local': False}
    
    if rssi is not None:
        signal_stats[node_id]['rssi'].append(rssi)
        # Keep only last 10 readings
        if len(signal_stats[node_id]['rssi']) > 10:
            signal_stats[node_id]['rssi'].pop(0)
    
    if snr is not None:
        signal_stats[node_id]['snr'].append(snr)
        # Keep only last 10 readings
        if len(signal_stats[node_id]['snr']) > 10:
            signal_stats[node_id]['snr'].pop(0)
    
    # Analyze if this is a local node
    analyze_local_node(node_id)

def analyze_local_node(node_id):
    """Analyze if a node is a local (1-hop) neighbor based on signal strength"""
    if node_id not in signal_stats:
        return
    
    stats = signal_stats[node_id]
    
    # Need at least 3 readings to make a determination
    if len(stats['rssi']) < 3:
        return
    
    # Calculate average signal strength
    avg_rssi = sum(stats['rssi']) / len(stats['rssi'])
    avg_snr = sum(stats['snr']) / len(stats['snr']) if stats['snr'] else 0
    
    # Thresholds for local node detection
    # These are typical values - may need adjustment based on your environment
    LOCAL_RSSI_THRESHOLD = -60  # dB - signals stronger than this are likely local
    LOCAL_SNR_THRESHOLD = 5     # dB - SNR higher than this indicates good local connection
    
    # Consider a node local if it consistently has strong signal
    is_local = (avg_rssi > LOCAL_RSSI_THRESHOLD and 
                avg_snr > LOCAL_SNR_THRESHOLD and 
                max(stats['rssi']) > LOCAL_RSSI_THRESHOLD - 10)  # At least one very strong reading
    
    stats['is_local'] = is_local
    
    # Update node_info if this node exists
    if node_id in node_info:
        node_info[node_id]['is_local'] = is_local
        node_info[node_id]['avg_rssi'] = avg_rssi
        node_info[node_id]['avg_snr'] = avg_snr

def get_local_nodes():
    """Get list of identified local nodes"""
    local_nodes = []
    for node_id, stats in signal_stats.items():
        if stats['is_local']:
            local_nodes.append(node_id)
    return local_nodes

def display_local_nodes():
    """Display information about identified local nodes"""
    local_nodes = get_local_nodes()
    if not local_nodes:
        return
    
    print(f"  Local nodes ({len(local_nodes)} identified):")
    for node_id in local_nodes:
        if node_id in node_info:
            node_data = node_info[node_id]
            short_name = node_data.get('short_name', '')
            long_name = node_data.get('long_name', '')
            node_name = short_name or long_name or node_id
            
            stats = signal_stats.get(node_id, {})
            avg_rssi = stats.get('avg_rssi', 0)
            avg_snr = stats.get('avg_snr', 0)
            
            print(f"    🔗 {node_name} (RSSI: {avg_rssi:.1f}dB, SNR: {avg_snr:.1f}dB)")
    
    # Clean up old signal stats (keep last 100 nodes)
    if len(signal_stats) > 100:
        # Remove oldest entries (simple FIFO)
        oldest_nodes = list(signal_stats.keys())[:len(signal_stats) - 100]
        for old_node in oldest_nodes:
            del signal_stats[old_node]

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
    client = mqtt.Client(protocol=mqtt.MQTTv311)
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
