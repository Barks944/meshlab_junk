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
packet_stats = {'total': 0, 'by_type': {}, 'by_hops': {}, 'direct_packets': 0}

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
    
    # Check for 1-hop indicators (MQTT packets may not have explicit hop info)
    hops = packet_data.get('hops', -1)
    portnum = packet_data.get('portnum', packet_data.get('portNum', -1))
    
    # For MQTT packets, check payload for additional info
    payload = packet_data.get('payload', {})
    if isinstance(payload, dict):
        hops = payload.get('hops', payload.get('hop_count', hops))
        portnum = payload.get('portnum', payload.get('portNum', portnum))
    
    # Debug: show packet structure info
    if packet_stats['total'] <= 5:  # Only show for first few packets
        print(f"  Debug: portnum={portnum}, hops={hops}, payload_keys={list(payload.keys()) if isinstance(payload, dict) else 'N/A'}")
    
    is_direct_packet = False
    
    # Method 1: Monitor 0-Hop Packets (if available)
    if hops == 0:
        is_direct_packet = True
        print("  📡 Direct RF reception (0 hops)")
    
    # Method 2: Telemetry Packets (portnum == 3, typically direct)
    elif packet_type == 'telemetry':
        is_direct_packet = True
        print("  🔋 Telemetry packet (likely direct)")
    
    # Method 3: Position Packets (typically direct)
    elif packet_type == 'position':
        is_direct_packet = True
        print("  📍 Position packet (likely direct)")
    
    # Method 4: Detection Sensor Packets (portnum == 6)
    elif portnum == 6:
        is_direct_packet = True
        print("  🔔 Detection sensor packet (likely direct)")
    
    # Method 5: Neighbor Info Module
    elif portnum == 6 and packet_type == 'module':
        if 'neighbors' in str(payload).lower() or 'neighborinfo' in str(payload).lower():
            is_direct_packet = True
            print("  👥 Neighbor info packet")
    
    # Method 6: Strong signal packets (likely direct to gateway)
    elif rssi is not None and rssi > -90:  # Strong signal threshold
        is_direct_packet = True
        print("  📡 Strong signal packet (likely direct)")
    
    # Method 7: Range Test packets
    elif 'range' in packet_type.lower() or 'test' in packet_type.lower():
        is_direct_packet = True
        print("  🎯 Range test packet")
    
    # Mark as confirmed 1-hop if any direct indicator is found
    if is_direct_packet and from_hex:
        if from_hex not in signal_stats:
            signal_stats[from_hex] = {'rssi': [], 'snr': [], 'is_local': False, 'confirmed_1hop': False}
        signal_stats[from_hex]['confirmed_1hop'] = True
        signal_stats[from_hex]['is_local'] = True  # Override RSSI/SNR analysis for confirmed direct packets
        
        # Update node_info
        if from_hex in node_info:
            node_info[from_hex]['is_local'] = True
            node_info[from_hex]['confirmed_1hop'] = True
        else:
            node_info[from_hex] = {
                'is_local': True,
                'confirmed_1hop': True,
                'last_seen': datetime.now().isoformat()
            }
    
    # Get node name if available
    node_name = ""
    if from_hex in node_info:
        short_name = node_info[from_hex].get('short_name', '')
        long_name = node_info[from_hex].get('long_name', '')
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
    
    print(f"\n[{datetime.now()}] Received {packet_type} packet from {from_hex}{node_name}")
    
    # Show hop information
    if hops >= 0:
        hop_info = f"{hops} hop{'s' if hops != 1 else ''}"
        if hops == 0:
            hop_info += " (direct RF)"
        print(f"  📡 {hop_info}")
    elif is_direct_packet:
        print("  📡 Likely direct (based on packet type/signal)")
    else:
        print("  📡 Hop count unknown")
    
    # Show signal strength info
    if rssi is not None or snr is not None:
        signal_info = []
        if rssi is not None:
            signal_info.append(f"RSSI: {rssi}dB")
        if snr is not None:
            signal_info.append(f"SNR: {snr}dB")
        if signal_info:
            print(f"  📶 {', '.join(signal_info)}")
    
    # Update packet statistics
    packet_stats['total'] += 1
    
    # Track by packet type
    if packet_type not in packet_stats['by_type']:
        packet_stats['by_type'][packet_type] = 0
    packet_stats['by_type'][packet_type] += 1
    
    # Track by hops
    if hops not in packet_stats['by_hops']:
        packet_stats['by_hops'][hops] = 0
    packet_stats['by_hops'][hops] += 1
    
    # Track direct packets
    if is_direct_packet:
        packet_stats['direct_packets'] += 1
    
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
    
    # Display local nodes and packet statistics periodically
    if len(packet_history) % 20 == 0:  # Every 20 packets
        display_local_nodes()
        display_packet_stats()
    
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
        signal_stats[node_id] = {'rssi': [], 'snr': [], 'is_local': False, 'confirmed_1hop': False}
    
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
    
    # If already confirmed as 1-hop, keep it marked as local
    if stats.get('confirmed_1hop', False):
        stats['is_local'] = True
        if node_id in node_info:
            node_info[node_id]['is_local'] = True
            node_info[node_id]['confirmed_1hop'] = True
        return
    
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
    
    confirmed_count = sum(1 for node_id in local_nodes if signal_stats.get(node_id, {}).get('confirmed_1hop', False))
    estimated_count = len(local_nodes) - confirmed_count
    
    print(f"  Local nodes ({len(local_nodes)} identified: {confirmed_count} confirmed, {estimated_count} estimated):")
    for node_id in local_nodes:
        if node_id in node_info:
            node_data = node_info[node_id]
            short_name = node_data.get('short_name', '')
            long_name = node_data.get('long_name', '')
            node_name = short_name or long_name or node_id
            
            stats = signal_stats.get(node_id, {})
            avg_rssi = stats.get('avg_rssi', 0)
            avg_snr = stats.get('avg_snr', 0)
            is_confirmed = stats.get('confirmed_1hop', False)
            
            # Show different icons for confirmed vs estimated
            icon = "🔗" if is_confirmed else "📶"
            status = "confirmed" if is_confirmed else "estimated"
            
            print(f"    {icon} {node_name} ({status}) - RSSI: {avg_rssi:.1f}dB, SNR: {avg_snr:.1f}dB")
    
    # Clean up old signal stats (keep last 100 nodes)
    if len(signal_stats) > 100:
        # Remove oldest entries (simple FIFO)
        oldest_nodes = list(signal_stats.keys())[:len(signal_stats) - 100]
        for old_node in oldest_nodes:
            del signal_stats[old_node]

def display_packet_stats():
    """Display packet statistics"""
    if packet_stats['total'] == 0:
        return
    
    print(f"\n📊 Packet Statistics (Total: {packet_stats['total']}):")
    
    # Packet types
    print("  By Type:")
    for packet_type, count in sorted(packet_stats['by_type'].items()):
        percentage = (count / packet_stats['total']) * 100
        print(f"    {packet_type}: {count} ({percentage:.1f}%)")
    
    # Hop distribution
    print("  By Hops:")
    for hops, count in sorted(packet_stats['by_hops'].items()):
        if hops == -1:
            hop_desc = "unknown"
        elif hops == 0:
            hop_desc = "direct (0)"
        else:
            hop_desc = f"{hops}"
        percentage = (count / packet_stats['total']) * 100
        print(f"    {hop_desc} hops: {count} ({percentage:.1f}%)")
    
    # Direct packets (detected by various methods)
    direct_percentage = (packet_stats['direct_packets'] / packet_stats['total']) * 100
    print(f"  Likely direct packets: {packet_stats['direct_packets']} ({direct_percentage:.1f}%)")

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
