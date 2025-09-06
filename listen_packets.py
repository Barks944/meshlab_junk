import meshtastic
import meshtastic.tcp_interface
from datetime import datetime
import time
import threading
import argparse
import sys
import socket
import logging
import re
import os
import signal

DEVICE_IP = "192.168.86.39"

# Global node name cache
node_names = {}

# Global flag to track connection errors from meshtastic library
connection_error_detected = False

class MeshtasticErrorHandler(logging.Handler):
    """Custom logging handler to detect meshtastic connection errors"""
    
    def emit(self, record):
        global connection_error_detected
        message = self.format(record)
        
        # Check for connection-related error patterns
        connection_error_patterns = [
            r'WinError 10054',  # Connection forcibly closed
            r'Connection.*closed',
            r'Unexpected OSError.*terminating meshtastic reader',
            r'Connection.*lost',
            r'Network.*error',
            r'terminating meshtastic reader'
        ]
        
        for pattern in connection_error_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DETECTED CONNECTION ERROR: {message}")
                connection_error_detected = True
                break

def parse_arguments():
    parser = argparse.ArgumentParser(description='Listen to Meshtastic packets with filtering options')
    parser.add_argument('--filter-type', nargs='*', help='Filter by message types (e.g., NodeInfo, MeshPacket, Config, Channel)')
    parser.add_argument('--filter-node', nargs='*', help='Filter by node IDs (hex format like 0x9eecae9c or names)')
    parser.add_argument('--filter-port', nargs='*', help='Filter by port numbers or names (e.g., 1, TEXT_MESSAGE_APP)')
    parser.add_argument('--exclude-type', nargs='*', help='Exclude message types')
    parser.add_argument('--exclude-node', nargs='*', help='Exclude node IDs or names')
    parser.add_argument('--show-unknown', action='store_true', help='Show unknown message types (default: hidden)')
    parser.add_argument('--quiet-sync', action='store_true', help='Hide repetitive sync messages (Config, ModuleConfig)')
    parser.add_argument('--packets-only', action='store_true', help='Show only decoded application layer packets (PACKET messages), hide FROM_RADIO transport layer')
    parser.add_argument('--show-text', action='store_true', help='Display text message content in packet logs')
    parser.add_argument('--no-reconnect', action='store_true', help='Disable automatic reconnection on connection errors')
    parser.add_argument('--reconnect-delay', type=int, default=5, help='Delay in seconds between reconnection attempts (default: 5)')
    parser.add_argument('--list-ports', action='store_true', help='List known Meshtastic port types and exit')
    return parser.parse_args()

def list_port_types():
    """Display known Meshtastic port types"""
    print("Known Meshtastic Port Types (PortNum):")
    print("="*50)
    port_types = [
        ("1", "TEXT_MESSAGE_APP", "Plain text messages between nodes"),
        ("2", "ROUTING_APP", "ACKs, NACKs, routing messages"),
        ("3", "POSITION_APP", "GPS/location data"),
        ("4", "NODEINFO_APP", "Node information (ID, hardware, firmware)"),
        ("5", "NEIGHBORINFO_APP", "Information about neighboring nodes"),
        ("6", "ADMIN_APP", "Administrative tasks, configuration"),
        ("32", "REPLY_APP", "Reply messages"),
        ("33", "IP_TUNNEL_APP", "IP tunneling over mesh"),
        ("34", "WAYPOINT_APP", "Points of interest, markers"),
        ("35", "PAXCOUNTER_APP", "People/device counter"),
        ("64", "REMOTE_HARDWARE_APP/SERIAL_APP", "Remote hardware control/Serial"),
        ("65", "AUDIO_APP", "Voice data (experimental)"),
        ("66", "STORE_FORWARD_APP", "Store and forward messages"),
        ("67", "TELEMETRY_APP", "Sensor data, battery, environment"),
        ("68", "DETECTION_SENSOR_APP", "Detection sensors"),
        ("69", "RANGE_TEST_APP", "Range testing"),
        ("70", "TRACEROUTE_APP", "Network path tracing"),
        ("72", "ATAK_PLUGIN", "ATAK (military/tactical) plugin"),
    ]
    
    for port_num, port_name, description in port_types:
        print(f"{port_num:>3}: {port_name:<22} - {description}")
    
    print("\nMessage Types:")
    print("="*30)
    msg_types = [
        "MeshPacket", "NodeInfo", "MyNodeInfo", "Config", "ModuleConfig", 
        "Channel", "ConfigComplete", "LogRecord", "Unknown"
    ]
    for msg_type in msg_types:
        print(f"  {msg_type}")
    
    print("\nExample Usage:")
    print("-"*30)
    print("# Show only application layer packets with node names:")
    print("python listen_packets.py --packets-only")
    print()
    print("# Show only text messages:")
    print("python listen_packets.py --filter-port TEXT_MESSAGE_APP")
    print()
    print("# Show text messages with content displayed:")
    print("python listen_packets.py --filter-port TEXT_MESSAGE_APP --show-text")
    print()
    print("# Show only telemetry data:")
    print("python listen_packets.py --filter-port TELEMETRY_APP")
    print()
    print("# Clean view without sync spam:")
    print("python listen_packets.py --quiet-sync")
    print()
    print("# Monitor specific node:")
    print("python listen_packets.py --filter-node ALBU")
    print()
    print("# Show everything including unknown packets:")
    print("python listen_packets.py --show-unknown")
    print()
    print("# Application layer only (no transport layer FROM_RADIO messages):")
    print("python listen_packets.py --packets-only")
    print()
    print("# Show text content for all packets that contain text:")
    print("python listen_packets.py --show-text")
    print()
    print("# Disable auto-reconnection (for testing):")
    print("python listen_packets.py --no-reconnect")
    print()
    print("# Custom reconnection delay:")
    print("python listen_packets.py --reconnect-delay 10")

def should_show_message(msg_type, node_id, node_name, port_info, args):
    """Determine if a message should be displayed based on filters"""
    
    # Handle quiet-sync mode
    if args.quiet_sync and msg_type in ['Config', 'ModuleConfig', 'Channel']:
        return False
    
    # Handle unknown messages
    if msg_type == 'Unknown' and not args.show_unknown:
        return False
    
    # Handle exclude filters first
    if args.exclude_type and msg_type in args.exclude_type:
        return False
    
    if args.exclude_node:
        for exclude_node in args.exclude_node:
            if exclude_node.lower() in [str(node_id).lower(), str(node_name).lower()]:
                return False
    
    # Handle include filters
    show_by_type = not args.filter_type or msg_type in args.filter_type
    
    show_by_node = True
    if args.filter_node:
        show_by_node = False
        for filter_node in args.filter_node:
            if filter_node.lower() in [str(node_id).lower(), str(node_name).lower()]:
                show_by_node = True
                break
    
    show_by_port = True
    if args.filter_port and port_info:
        show_by_port = False
        for filter_port in args.filter_port:
            if filter_port.lower() in port_info.lower():
                show_by_port = True
                break
    
    return show_by_type and show_by_node and show_by_port

def connect_with_retry(device_ip, args):
    """Connect to Meshtastic device with automatic retry logic"""
    attempt = 1
    max_attempts = 999999 if not args.no_reconnect else 1
    
    while attempt <= max_attempts:
        try:
            if attempt > 1:
                print(f"Reconnecting to Meshtastic device at {device_ip}... (attempt {attempt})")
            else:
                print(f"Connecting to Meshtastic device at {device_ip}... (attempt {attempt})")
            interface = meshtastic.tcp_interface.TCPInterface(device_ip)
            print("Connected successfully!")
            return interface
        except (socket.error, OSError, ConnectionError, Exception) as e:
            error_msg = str(e)
            print(f"Connection failed (attempt {attempt}): {error_msg}")
            
            if args.no_reconnect or attempt >= max_attempts:
                print("Giving up on connection.")
                raise e
            
            print(f"Waiting {args.reconnect_delay} seconds before retry...")
            time.sleep(args.reconnect_delay)
            attempt += 1
    
    return None

def listen_with_reconnect(args):
    """Main listening loop with reconnection handling"""
    global connection_error_detected
    interface = None
    connection_lost = False
    
    while True:
        try:
            # Connect or reconnect to device
            if interface is None:
                if connection_lost:
                    print(f"\n--- RECONNECTING ---")
                # Reset the error flag before attempting connection
                connection_error_detected = False
                interface = connect_with_retry(DEVICE_IP, args)
                if interface is None:
                    break
                connection_lost = False
                
                # Store original handlers
                original_packet_handler = interface._handlePacketFromRadio
                original_from_radio = interface._handleFromRadio
                
                def packet_handler(meshPacket, hack=False):
                    try:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Extract comprehensive packet information
                        packet_info = []
                        node_id = None
                        node_name = ""
                        from_name = ""
                        to_name = ""
                        
                        # Basic packet info
                        if hasattr(meshPacket, 'id'):
                            packet_info.append(f"ID:{meshPacket.id}")
                        if hasattr(meshPacket, 'from') and getattr(meshPacket, 'from'):
                            node_id = hex(getattr(meshPacket, 'from'))
                            # Look up the friendly name
                            from_name = node_names.get(node_id, node_id)
                            packet_info.append(f"From:{from_name}")
                        if hasattr(meshPacket, 'to') and meshPacket.to:
                            to_id = hex(meshPacket.to)
                            if to_id == "0xffffffff":
                                to_name = "BROADCAST"
                            else:
                                to_name = node_names.get(to_id, to_id)
                            packet_info.append(f"To:{to_name}")
                        if hasattr(meshPacket, 'channel'):
                            packet_info.append(f"Ch:{meshPacket.channel}")
                        if hasattr(meshPacket, 'hop_limit'):
                            packet_info.append(f"Hops:{meshPacket.hop_limit}")
                        if hasattr(meshPacket, 'want_ack'):
                            packet_info.append(f"WantAck:{meshPacket.want_ack}")
                        if hasattr(meshPacket, 'rx_time'):
                            packet_info.append(f"RxTime:{meshPacket.rx_time}")
                        if hasattr(meshPacket, 'rx_snr'):
                            packet_info.append(f"SNR:{meshPacket.rx_snr}")
                        if hasattr(meshPacket, 'rx_rssi'):
                            packet_info.append(f"RSSI:{meshPacket.rx_rssi}")
                        
                        # Decode payload information
                        payload_info = "NoPayload"
                        port_name = ""
                        if hasattr(meshPacket, 'decoded') and meshPacket.decoded:
                            decoded = meshPacket.decoded
                            if hasattr(decoded, 'portnum'):
                                # Handle both enum objects and integer values for portnum
                                port_name = decoded.portnum.name if hasattr(decoded.portnum, 'name') else str(decoded.portnum)
                                payload_info = f"Port:{port_name}"
                                
                                # Add specific payload data based on port type
                                if hasattr(decoded, 'payload'):
                                    try:
                                        if (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'TEXT_MESSAGE_APP') or decoded.portnum == 1:
                                            text_content = None
                                            # First try the decoded.text field
                                            if hasattr(decoded, 'text') and decoded.text:
                                                text_content = decoded.text
                                            # If that's empty, try decoding the raw payload as UTF-8
                                            elif hasattr(decoded, 'payload') and decoded.payload:
                                                try:
                                                    text_content = decoded.payload.decode('utf-8')
                                                except UnicodeDecodeError:
                                                    text_content = decoded.payload.decode('utf-8', errors='replace')
                                            
                                            if text_content:
                                                if args.show_text:
                                                    payload_info += f" Text:'{text_content}'"
                                                else:
                                                    payload_info += f" TextLen:{len(text_content)}"
                                            else:
                                                payload_info += f" Text:(no content found)"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'NODEINFO_APP') or decoded.portnum == 4:
                                            if hasattr(decoded, 'user'):
                                                user = decoded.user
                                                user_info = []
                                                if hasattr(user, 'short_name'):
                                                    user_info.append(f"Name:{user.short_name}")
                                                    node_name = user.short_name
                                                    # Cache this name too
                                                    if node_id:
                                                        node_names[node_id] = user.short_name
                                                if hasattr(user, 'long_name'):
                                                    user_info.append(f"Long:{user.long_name}")
                                                if hasattr(user, 'macaddr'):
                                                    user_info.append(f"MAC:{user.macaddr.hex()}")
                                                if hasattr(user, 'hw_model'):
                                                    hw_model_name = user.hw_model.name if hasattr(user.hw_model, 'name') else str(user.hw_model)
                                                    user_info.append(f"HW:{hw_model_name}")
                                                if hasattr(user, 'role'):
                                                    role_name = user.role.name if hasattr(user.role, 'name') else str(user.role)
                                                    user_info.append(f"Role:{role_name}")
                                                payload_info += f" User:[{','.join(user_info)}]"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'POSITION_APP') or decoded.portnum == 3:
                                            if hasattr(decoded, 'position'):
                                                pos = decoded.position
                                                pos_info = []
                                                if hasattr(pos, 'latitude_i') and pos.latitude_i:
                                                    pos_info.append(f"Lat:{pos.latitude_i/1e7:.6f}")
                                                if hasattr(pos, 'longitude_i') and pos.longitude_i:
                                                    pos_info.append(f"Lon:{pos.longitude_i/1e7:.6f}")
                                                if hasattr(pos, 'altitude'):
                                                    pos_info.append(f"Alt:{pos.altitude}m")
                                                if hasattr(pos, 'time'):
                                                    pos_info.append(f"Time:{pos.time}")
                                                if hasattr(pos, 'PDOP'):
                                                    pos_info.append(f"PDOP:{pos.PDOP}")
                                                payload_info += f" Pos:[{','.join(pos_info)}]"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'TELEMETRY_APP') or decoded.portnum == 67:
                                            if hasattr(decoded, 'telemetry'):
                                                tel = decoded.telemetry
                                                tel_info = []
                                                if hasattr(tel, 'device_metrics'):
                                                    dm = tel.device_metrics
                                                    if hasattr(dm, 'battery_level'):
                                                        tel_info.append(f"Batt:{dm.battery_level}%")
                                                    if hasattr(dm, 'voltage'):
                                                        tel_info.append(f"V:{dm.voltage:.2f}")
                                                    if hasattr(dm, 'channel_utilization'):
                                                        tel_info.append(f"ChUtil:{dm.channel_utilization:.1f}%")
                                                    if hasattr(dm, 'air_util_tx'):
                                                        tel_info.append(f"AirTx:{dm.air_util_tx:.1f}%")
                                                    if hasattr(dm, 'uptime_seconds'):
                                                        tel_info.append(f"Uptime:{dm.uptime_seconds}s")
                                                if hasattr(tel, 'environment_metrics'):
                                                    em = tel.environment_metrics
                                                    if hasattr(em, 'temperature'):
                                                        tel_info.append(f"Temp:{em.temperature:.1f}°C")
                                                    if hasattr(em, 'relative_humidity'):
                                                        tel_info.append(f"Humidity:{em.relative_humidity:.1f}%")
                                                    if hasattr(em, 'barometric_pressure'):
                                                        tel_info.append(f"Pressure:{em.barometric_pressure:.1f}hPa")
                                                payload_info += f" Tel:[{','.join(tel_info)}]"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'ROUTING_APP') or decoded.portnum == 2:
                                            if hasattr(decoded, 'routing'):
                                                routing = decoded.routing
                                                if hasattr(routing, 'error_reason'):
                                                    error_name = routing.error_reason.name if hasattr(routing.error_reason, 'name') else str(routing.error_reason)
                                                    payload_info += f" Error:{error_name}"
                                                else:
                                                    payload_info += f" ACK"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'ADMIN_APP') or decoded.portnum == 6:
                                            payload_info += f" Admin"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'REMOTE_HARDWARE_APP') or decoded.portnum == 64:
                                            payload_info += f" RemoteHW"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'WAYPOINT_APP') or decoded.portnum == 34:
                                            if hasattr(decoded, 'waypoint'):
                                                wp = decoded.waypoint
                                                wp_info = []
                                                if hasattr(wp, 'name'):
                                                    wp_info.append(f"Name:{wp.name}")
                                                if hasattr(wp, 'latitude_i') and wp.latitude_i:
                                                    wp_info.append(f"Lat:{wp.latitude_i/1e7:.6f}")
                                                if hasattr(wp, 'longitude_i') and wp.longitude_i:
                                                    wp_info.append(f"Lon:{wp.longitude_i/1e7:.6f}")
                                                payload_info += f" Waypoint:[{','.join(wp_info)}]"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'NEIGHBORINFO_APP') or decoded.portnum == 5:
                                            payload_info += f" NeighborInfo"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'TRACEROUTE_APP') or decoded.portnum == 70:
                                            if hasattr(decoded, 'route'):
                                                route = decoded.route
                                                if hasattr(route, 'route') and route.route:
                                                    route_nodes = [node_names.get(hex(node), hex(node)) for node in route.route]
                                                    payload_info += f" Route:[{' -> '.join(route_nodes)}]"
                                                else:
                                                    payload_info += f" TraceRoute"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'AUDIO_APP') or decoded.portnum == 65:
                                            payload_info += f" Audio"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'DETECTION_SENSOR_APP') or decoded.portnum == 68:
                                            payload_info += f" Detection"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'REPLY_APP') or decoded.portnum == 32:
                                            payload_info += f" Reply"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'IP_TUNNEL_APP') or decoded.portnum == 33:
                                            payload_info += f" IPTunnel"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'PAXCOUNTER_APP') or decoded.portnum == 35:
                                            payload_info += f" PaxCounter"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'SERIAL_APP') or decoded.portnum == 64:
                                            payload_info += f" Serial"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'STORE_FORWARD_APP') or decoded.portnum == 66:
                                            payload_info += f" StoreForward"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'RANGE_TEST_APP') or decoded.portnum == 69:
                                            payload_info += f" RangeTest"
                                        elif (hasattr(decoded.portnum, 'name') and decoded.portnum.name == 'ATAK_PLUGIN') or decoded.portnum == 72:
                                            payload_info += f" ATAK"
                                        else:
                                            # For other payload types, show basic info
                                            payload_info += f" PayloadSize:{len(decoded.payload)} bytes"
                                    except Exception as e:
                                        payload_info += f" (decode error: {str(e)[:30]})"
                        
                        # Check if this message should be shown
                        if should_show_message("MeshPacket", node_id, from_name, port_name, args):
                            # Combine all information into a single line
                            info_parts = packet_info + [payload_info]
                            packet_summary = " | ".join(info_parts)
                            
                            print(f"[{timestamp}] PACKET: {packet_summary}")
                        
                        # Call the original handler to maintain normal operation
                        return original_packet_handler(meshPacket, hack)
                    except (socket.error, OSError, ConnectionError) as e:
                        # Check for WinError 10054 specifically
                        error_msg = str(e)
                        if "10054" in error_msg or "forcibly closed" in error_msg.lower():
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DETECTED CONNECTION ERROR: {error_msg}")
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exiting due to connection error...")
                            sys.exit(1)
                        # Re-raise other connection errors so they can be caught by the main loop
                        raise e
                    except Exception as e:
                        # For other errors, log and continue
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] PACKET HANDLER ERROR: {e}")
                        return None
                
                def from_radio_handler(fromRadioBytes):
                    try:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        # Try to decode the protobuf message for more info
                        try:
                            from meshtastic.protobuf import mesh_pb2
                            from_radio = mesh_pb2.FromRadio()
                            from_radio.ParseFromString(fromRadioBytes)
                            
                            msg_type = "Unknown"
                            extra_info = []
                            node_id = None
                            node_name = ""
                            
                            if from_radio.HasField('packet'):
                                msg_type = "MeshPacket"
                                packet = from_radio.packet
                                if hasattr(packet, 'from') and getattr(packet, 'from'):
                                    node_id = hex(getattr(packet, 'from'))
                                    extra_info.append(f"From:{node_id}")
                                if hasattr(packet, 'to') and packet.to:
                                    extra_info.append(f"To:{hex(packet.to)}")
                            elif from_radio.HasField('my_info'):
                                msg_type = "MyNodeInfo"
                                info = from_radio.my_info
                                if hasattr(info, 'my_node_num'):
                                    node_id = hex(info.my_node_num)
                                    extra_info.append(f"NodeNum:{node_id}")
                            elif from_radio.HasField('node_info'):
                                msg_type = "NodeInfo"
                                node = from_radio.node_info
                                if hasattr(node, 'num'):
                                    node_id = hex(node.num)
                                    extra_info.append(f"NodeNum:{node_id}")
                                if hasattr(node, 'user') and hasattr(node.user, 'short_name'):
                                    node_name = node.user.short_name
                                    extra_info.append(f"Name:{node_name}")
                                    # Cache the node name for later use
                                    if node_id:
                                        node_names[node_id] = node_name
                            elif from_radio.HasField('config'):
                                msg_type = "Config"
                                config = from_radio.config
                                # Try to identify which config section
                                if hasattr(config, 'device') and config.HasField('device'):
                                    extra_info.append("Section:Device")
                                elif hasattr(config, 'position') and config.HasField('position'):
                                    extra_info.append("Section:Position")
                                elif hasattr(config, 'power') and config.HasField('power'):
                                    extra_info.append("Section:Power")
                                elif hasattr(config, 'network') and config.HasField('network'):
                                    extra_info.append("Section:Network")
                                elif hasattr(config, 'display') and config.HasField('display'):
                                    extra_info.append("Section:Display")
                                elif hasattr(config, 'lora') and config.HasField('lora'):
                                    extra_info.append("Section:LoRa")
                                elif hasattr(config, 'bluetooth') and config.HasField('bluetooth'):
                                    extra_info.append("Section:Bluetooth")
                            elif from_radio.HasField('log_record'):
                                msg_type = "LogRecord"
                                log = from_radio.log_record
                                if hasattr(log, 'level'):
                                    extra_info.append(f"Level:{log.level}")
                            elif from_radio.HasField('config_complete_id'):
                                msg_type = "ConfigComplete"
                                extra_info.append(f"ID:{from_radio.config_complete_id}")
                            elif from_radio.HasField('rebooted'):
                                msg_type = "Rebooted"
                            elif from_radio.HasField('moduleConfig'):
                                msg_type = "ModuleConfig"
                            elif from_radio.HasField('channel'):
                                msg_type = "Channel"
                                channel = from_radio.channel
                                if hasattr(channel, 'index'):
                                    extra_info.append(f"Index:{channel.index}")
                            else:
                                # Try to identify unknown messages by examining the raw bytes
                                if len(fromRadioBytes) == 4:
                                    # Might be a simple numeric value
                                    import struct
                                    try:
                                        val = struct.unpack('<I', fromRadioBytes)[0]
                                        extra_info.append(f"Value:{val}")
                                    except:
                                        pass
                                elif len(fromRadioBytes) < 10:
                                    # Short message, show hex
                                    extra_info.append(f"Hex:{fromRadioBytes.hex()}")
                            
                            # Skip FROM_RADIO messages if packets-only mode is enabled
                            if args.packets_only:
                                return original_from_radio(fromRadioBytes)
                            
                            # Check if this message should be shown
                            if should_show_message(msg_type, node_id, node_name, None, args):
                                # Build the output string
                                info_str = f"{len(fromRadioBytes)} bytes | Type:{msg_type}"
                                if extra_info:
                                    info_str += f" | {' | '.join(extra_info)}"
                                
                                # Add raw bytes at the end (show first 32 bytes for readability)
                                bytes_to_show = fromRadioBytes[:32] if len(fromRadioBytes) > 32 else fromRadioBytes
                                info_str += f" | Bytes:{bytes_to_show.hex()}"
                                if len(fromRadioBytes) > 32:
                                    info_str += f"...({len(fromRadioBytes)} total)"
                                
                                print(f"[{timestamp}] FROM_RADIO: {info_str}")
                            
                        except Exception as e:
                            # Show raw bytes even on decode error (if not filtered out)
                            if not args.packets_only and should_show_message("Unknown", None, "", None, args):
                                bytes_to_show = fromRadioBytes[:32] if len(fromRadioBytes) > 32 else fromRadioBytes
                                error_info = f"{len(fromRadioBytes)} bytes | Raw data (decode error: {str(e)[:30]}) | Bytes:{bytes_to_show.hex()}"
                                if len(fromRadioBytes) > 32:
                                    error_info += f"...({len(fromRadioBytes)} total)"
                                print(f"[{timestamp}] FROM_RADIO: {error_info}")
                        
                        # Call the original handler to maintain normal operation
                        return original_from_radio(fromRadioBytes)
                    except (socket.error, OSError, ConnectionError) as e:
                        # Check for WinError 10054 specifically
                        error_msg = str(e)
                        if "10054" in error_msg or "forcibly closed" in error_msg.lower():
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DETECTED CONNECTION ERROR: {error_msg}")
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exiting due to connection error...")
                            sys.exit(1)
                        # Re-raise other connection errors so they can be caught by the main loop
                        raise e
                    except Exception as e:
                        # For other errors, log and continue
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] FROM_RADIO HANDLER ERROR: {e}")
                        return None
                
                # Replace the handlers
                interface._handlePacketFromRadio = packet_handler
                interface._handleFromRadio = from_radio_handler
                
                print("Listening for received packets and radio data... (Press Ctrl+C to stop)")
                print("If you don't see packets, try sending a message from another device or the app")
            
            # Keep the script running and listening
            last_packet_time = time.time()
            while True:
                current_time = time.time()
                
                # Check for connection errors detected by our logging handler
                if connection_error_detected:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Meshtastic library reported connection error")
                    raise ConnectionError("Meshtastic library detected connection error")
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\nStopped listening.")
            break
        except (socket.error, OSError, ConnectionError) as e:
            error_msg = str(e)
            print(f"\nConnection error: {error_msg}")
            connection_lost = True
            
            # Clean up the failed interface
            if interface is not None:
                try:
                    interface.close()
                except:
                    pass
                interface = None
            
            if args.no_reconnect:
                print("Reconnection disabled. Exiting.")
                break
            
            print(f"Attempting to reconnect in {args.reconnect_delay} seconds...")
            time.sleep(args.reconnect_delay)
            continue
        except Exception as e:
            print(f"Unexpected error: {e}")
            connection_lost = True
            # Clean up the failed interface
            if interface is not None:
                try:
                    interface.close()
                except:
                    pass
                interface = None
                
            if args.no_reconnect:
                print("Reconnection disabled. Exiting.")
                break
                
            print(f"Attempting to reconnect in {args.reconnect_delay} seconds...")
            time.sleep(args.reconnect_delay)
            continue
        finally:
            if interface is not None:
                try:
                    interface.close()
                except:
                    pass

def main():
    global connection_error_detected
    args = parse_arguments()
    
    # Handle list-ports option
    if args.list_ports:
        list_port_types()
        return
    
    # Print active filters
    if any([args.filter_type, args.filter_node, args.filter_port, args.exclude_type, args.exclude_node, args.show_text]):
        print("Active filters:")
        if args.filter_type:
            print(f"  Include types: {', '.join(args.filter_type)}")
        if args.filter_node:
            print(f"  Include nodes: {', '.join(args.filter_node)}")
        if args.filter_port:
            print(f"  Include ports: {', '.join(args.filter_port)}")
        if args.exclude_type:
            print(f"  Exclude types: {', '.join(args.exclude_type)}")
        if args.exclude_node:
            print(f"  Exclude nodes: {', '.join(args.exclude_node)}")
        if args.quiet_sync:
            print(f"  Quiet sync mode: ON (hiding Config, ModuleConfig, Channel)")
        if not args.show_unknown:
            print(f"  Unknown messages: HIDDEN (use --show-unknown to display)")
        if args.show_text:
            print(f"  Show text content: ON")
        print()
    
    # Print reconnection settings
    if not args.no_reconnect:
        print(f"Auto-reconnect: ENABLED (delay: {args.reconnect_delay}s)")
    else:
        print("Auto-reconnect: DISABLED")
    print()
    
    # Suppress verbose logging from meshtastic library for cleaner output
    logging.getLogger('meshtastic').setLevel(logging.WARNING)
    
    # Add our custom error handler to detect meshtastic connection errors
    meshtastic_logger = logging.getLogger('meshtastic')
    error_handler = MeshtasticErrorHandler()
    error_handler.setLevel(logging.DEBUG)  # Catch all messages
    meshtastic_logger.addHandler(error_handler)
    
    # Also add to root logger in case meshtastic logs to root
    root_logger = logging.getLogger()
    root_logger.addHandler(error_handler)
    
    try:
        listen_with_reconnect(args)
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
        print("Note: Make sure your Meshtastic device has TCP server enabled")
        print("Try enabling it with: meshtastic --set network.wifi_enabled true")

if __name__ == "__main__":
    main()
