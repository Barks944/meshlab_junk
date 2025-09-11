#!/usr/bin/env python3
"""
Packet Sender Inference Demo

This script demonstrates how to use the PacketSenderInference module
to infer the sender of received packets when sender information is unclear.

Usage:
    python packet_sender_inference_demo.py --csv nodes.csv --packet-log packet_log.txt

Or interactively:
    python packet_sender_inference_demo.py --csv nodes.csv
"""

import argparse
import csv
import sys
from packet_sender_inference import PacketSenderInference, extract_packet_features

def load_nodes_from_csv(csv_path: str) -> dict:
    """Load node information from CSV file"""
    nodes = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                node_id = row.get('Node ID', '').strip()
                if node_id:
                    # Convert string values to appropriate types where needed
                    node_info = {}
                    for key, value in row.items():
                        if key == 'Node Number' and value:
                            node_info['node_number'] = value
                        elif key == 'SNR' and value:
                            try:
                                node_info['snr'] = float(value)
                            except ValueError:
                                pass
                        elif key in ['Latitude', 'Longitude', 'Altitude'] and value:
                            try:
                                node_info[key.lower()] = float(value)
                            except ValueError:
                                pass
                        else:
                            node_info[key.lower().replace(' ', '_')] = value
                    nodes[node_id] = node_info
        print(f"Loaded {len(nodes)} nodes from {csv_path}")
    except FileNotFoundError:
        print(f"Error: CSV file {csv_path} not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        sys.exit(1)

    return nodes

def analyze_packet_log(log_path: str, inference_engine: PacketSenderInference):
    """Analyze packets from a log file"""
    try:
        with open(log_path, 'r', encoding='utf-8') as logfile:
            for line_num, line in enumerate(logfile, 1):
                line = line.strip()
                if not line or 'PACKET:' not in line:
                    continue

                print(f"\n--- Analyzing Packet {line_num} ---")
                print(f"Raw: {line}")

                # Extract features from the packet line
                features = extract_packet_features(line)
                print(f"Extracted features: {features}")

                if not features:
                    print("No analyzable features found in this packet")
                    continue

                # Run inference
                candidates = inference_engine.infer_sender(features)

                if candidates:
                    print("Potential senders (ranked by confidence):")
                    for i, (node_id, score, reason) in enumerate(candidates[:5], 1):  # Top 5
                        node_name = inference_engine.known_nodes.get(node_id, {}).get('short_name', node_id)
                        print(".3f")
                else:
                    print("No sender candidates found")

    except FileNotFoundError:
        print(f"Error: Log file {log_path} not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading log file: {e}")
        sys.exit(1)

def interactive_demo(inference_engine: PacketSenderInference):
    """Interactive demo for testing inference with manual packet features"""
    print("\n=== Interactive Packet Sender Inference Demo ===")
    print("Enter packet features (press Enter for unknown/empty):")

    features = {}

    # Get SNR
    snr_input = input("SNR (dB, e.g., -10.5): ").strip()
    if snr_input:
        try:
            features['snr'] = float(snr_input)
        except ValueError:
            print("Invalid SNR value")

    # Get RSSI
    rssi_input = input("RSSI (dB, e.g., -80): ").strip()
    if rssi_input:
        try:
            features['rssi'] = float(rssi_input)
        except ValueError:
            print("Invalid RSSI value")

    # Get location
    lat_input = input("Latitude (decimal degrees, e.g., 37.7749): ").strip()
    lon_input = input("Longitude (decimal degrees, e.g., -122.4194): ").strip()
    if lat_input and lon_input:
        try:
            features['latitude'] = float(lat_input)
            features['longitude'] = float(lon_input)
        except ValueError:
            print("Invalid latitude/longitude values")

    # Get port
    port_input = input("Port/App (e.g., TEXT_MESSAGE_APP): ").strip()
    if port_input:
        features['port'] = port_input

    # Get payload size
    size_input = input("Payload size (bytes): ").strip()
    if size_input:
        try:
            features['payload_size'] = int(size_input)
        except ValueError:
            print("Invalid payload size")

    print(f"\nAnalyzing packet with features: {features}")

    if not features:
        print("No features provided. Cannot perform inference.")
        return

    # Run inference
    candidates = inference_engine.infer_sender(features)

    if candidates:
        print("\nPotential senders (ranked by confidence):")
        for i, (node_id, score, reason) in enumerate(candidates[:10], 1):  # Top 10
            node_name = inference_engine.known_nodes.get(node_id, {}).get('short_name', node_id)
            print(".3f")
    else:
        print("No sender candidates found with the given features")

def main():
    parser = argparse.ArgumentParser(description='Packet Sender Inference Demo')
    parser.add_argument('--csv', required=True, help='Path to CSV file with node information')
    parser.add_argument('--packet-log', help='Path to packet log file to analyze')
    parser.add_argument('--interactive', action='store_true', help='Run interactive demo instead of analyzing log')

    args = parser.parse_args()

    # Load node data
    nodes = load_nodes_from_csv(args.csv)

    if not nodes:
        print("No nodes loaded from CSV. Cannot perform inference.")
        sys.exit(1)

    # Create inference engine
    inference = PacketSenderInference(nodes)

    if args.interactive:
        interactive_demo(inference)
    elif args.packet_log:
        analyze_packet_log(args.packet_log, inference)
    else:
        print("Please specify either --packet-log or --interactive")
        parser.print_help()

if __name__ == "__main__":
    main()
