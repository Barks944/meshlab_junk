"""
Packet Sender Inference Module

This module provides algorithms to infer the sender of a received Meshtastic packet
when the sender information is not directly available or needs verification.

Algorithms include:
- Signal strength matching
- Location proximity
- Timing patterns
- Packet content analysis
"""

import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import logging

logger = logging.getLogger(__name__)

class PacketSenderInference:
    """
    Class for inferring packet senders using various algorithms
    """

    def __init__(self, known_nodes: Optional[Dict[str, Dict]] = None):
        """
        Initialize with known node information

        Args:
            known_nodes: Dict of node_id -> node_info from display_nodes
        """
        self.known_nodes = known_nodes or {}
        self.node_history = {}  # Track recent activity per node
        self.signal_profiles = {}  # Store typical SNR/RSSI patterns per node

    def update_known_nodes(self, nodes_data: Dict[str, Dict]):
        """Update the known nodes database"""
        self.known_nodes = nodes_data

    def infer_sender(self, packet_data: Dict[str, Any], algorithms: Optional[List[str]] = None) -> List[Tuple[str, float, str]]:
        """
        Infer the most likely sender of a packet using multiple algorithms

        Args:
            packet_data: Dictionary containing packet information
            algorithms: List of algorithms to use (default: all)

        Returns:
            List of tuples: (node_id, confidence_score, reason)
        """
        if algorithms is None:
            algorithms = ['signal', 'location', 'timing', 'content']

        candidates = {}

        # Run each algorithm
        for algo in algorithms:
            if algo == 'signal':
                results = self._infer_by_signal(packet_data)
            elif algo == 'location':
                results = self._infer_by_location(packet_data)
            elif algo == 'timing':
                results = self._infer_by_timing(packet_data)
            elif algo == 'content':
                results = self._infer_by_content(packet_data)
            else:
                continue

            # Combine results
            for node_id, score, reason in results:
                if node_id not in candidates:
                    candidates[node_id] = {'total_score': 0, 'reasons': []}
                candidates[node_id]['total_score'] += score
                candidates[node_id]['reasons'].append(reason)

        # Sort by total score
        sorted_candidates = []
        for node_id, data in candidates.items():
            avg_score = data['total_score'] / len(data['reasons'])
            combined_reason = '; '.join(data['reasons'])
            sorted_candidates.append((node_id, avg_score, combined_reason))

        sorted_candidates.sort(key=lambda x: x[1], reverse=True)
        return sorted_candidates

    def _infer_by_signal(self, packet_data: Dict[str, Any]) -> List[Tuple[str, float, str]]:
        """
        Infer sender based on signal strength patterns
        """
        results = []
        packet_snr = packet_data.get('snr')
        packet_rssi = packet_data.get('rssi')

        if packet_snr is None and packet_rssi is None:
            return results

        for node_id, node_info in self.known_nodes.items():
            node_snr = node_info.get('snr')
            if node_snr and packet_snr:
                # Calculate similarity score based on SNR difference
                snr_diff = abs(float(packet_snr) - float(node_snr))
                if snr_diff <= 5:  # Within 5dB
                    score = max(0, 1.0 - (snr_diff / 5.0))
                    results.append((node_id, score, f"SNR match ({packet_snr}dB vs {node_snr}dB)"))

            # Could also compare RSSI if available
            # Add more sophisticated signal analysis here

        return results

    def _infer_by_location(self, packet_data: Dict[str, Any]) -> List[Tuple[str, float, str]]:
        """
        Infer sender based on location proximity
        """
        results = []
        packet_lat = packet_data.get('latitude')
        packet_lon = packet_data.get('longitude')

        if not packet_lat or not packet_lon:
            return results

        try:
            packet_lat = float(packet_lat)
            packet_lon = float(packet_lon)
        except (ValueError, TypeError):
            return results

        for node_id, node_info in self.known_nodes.items():
            node_lat = node_info.get('latitude')
            node_lon = node_info.get('longitude')

            if node_lat and node_lon:
                try:
                    node_lat = float(node_lat)
                    node_lon = float(node_lon)

                    # Calculate distance in km
                    distance = self._calculate_distance(packet_lat, packet_lon, node_lat, node_lon)

                    # Score based on proximity (closer = higher score)
                    if distance <= 1:  # Within 1km
                        score = max(0.1, 1.0 - (distance / 1.0))
                        results.append((node_id, score, f"Location proximity ({distance:.2f}km away)"))
                    elif distance <= 10:  # Within 10km
                        score = max(0.05, 0.5 - (distance / 20.0))
                        results.append((node_id, score, f"Location proximity ({distance:.2f}km away)"))

                except (ValueError, TypeError):
                    continue

        return results

    def _infer_by_timing(self, packet_data: Dict[str, Any]) -> List[Tuple[str, float, str]]:
        """
        Infer sender based on timing patterns and recent activity
        """
        results = []
        current_time = time.time()

        # Look for nodes that have been recently active
        for node_id, node_info in self.known_nodes.items():
            last_heard = node_info.get('last_heard')
            if last_heard:
                try:
                    # Parse the last heard time
                    last_heard_time = datetime.strptime(last_heard, '%Y-%m-%d %H:%M:%S').timestamp()
                    time_diff = current_time - last_heard_time

                    # Score based on recency (more recent = higher score)
                    if time_diff <= 300:  # Within 5 minutes
                        score = max(0.1, 1.0 - (time_diff / 300.0))
                        results.append((node_id, score, f"Recent activity ({int(time_diff)}s ago)"))
                    elif time_diff <= 3600:  # Within 1 hour
                        score = max(0.05, 0.5 - (time_diff / 7200.0))
                        results.append((node_id, score, f"Recent activity ({int(time_diff/60)}min ago)"))

                except (ValueError, TypeError):
                    continue

        return results

    def _infer_by_content(self, packet_data: Dict[str, Any]) -> List[Tuple[str, float, str]]:
        """
        Infer sender based on packet content patterns
        """
        results = []
        port = packet_data.get('port')
        payload_size = packet_data.get('payload_size', 0)

        # Simple content-based heuristics
        for node_id, node_info in self.known_nodes.items():
            score = 0
            reasons = []

            # Example: Different nodes might have characteristic payload sizes
            # This is highly dependent on actual usage patterns

            # Example: Certain ports are more likely from certain node types
            if port == 'TELEMETRY_APP' and 'uptime' in str(node_info.get('uptime', '')):
                score += 0.3
                reasons.append("Telemetry packet from node with uptime data")

            if port == 'POSITION_APP' and node_info.get('latitude'):
                score += 0.2
                reasons.append("Position packet from node with known location")

            if reasons:
                combined_reason = '; '.join(reasons)
                results.append((node_id, score, combined_reason))

        return results

    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two points using Haversine formula
        Returns distance in kilometers
        """
        R = 6371  # Earth's radius in km

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = math.sin(dlat/2) * math.sin(dlat/2) + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2) * math.sin(dlon/2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        return R * c

    def update_signal_profile(self, node_id: str, snr: float, rssi: float):
        """
        Update the signal strength profile for a node
        """
        if node_id not in self.signal_profiles:
            self.signal_profiles[node_id] = {'snr': [], 'rssi': []}

        if snr is not None:
            self.signal_profiles[node_id]['snr'].append(snr)
            # Keep only last 10 readings
            self.signal_profiles[node_id]['snr'] = self.signal_profiles[node_id]['snr'][-10:]

        if rssi is not None:
            self.signal_profiles[node_id]['rssi'].append(rssi)
            self.signal_profiles[node_id]['rssi'] = self.signal_profiles[node_id]['rssi'][-10:]

    def get_signal_profile(self, node_id: str) -> Dict[str, float]:
        """
        Get average signal characteristics for a node
        """
        if node_id not in self.signal_profiles:
            return {}

        profile = {}
        snr_data = self.signal_profiles[node_id]['snr']
        rssi_data = self.signal_profiles[node_id]['rssi']

        if snr_data:
            profile['avg_snr'] = sum(snr_data) / len(snr_data)
            profile['snr_std'] = math.sqrt(sum((x - profile['avg_snr'])**2 for x in snr_data) / len(snr_data))

        if rssi_data:
            profile['avg_rssi'] = sum(rssi_data) / len(rssi_data)
            profile['rssi_std'] = math.sqrt(sum((x - profile['avg_rssi'])**2 for x in rssi_data) / len(rssi_data))

        return profile


def extract_packet_features(packet_line: str) -> Dict[str, Any]:
    """
    Extract features from a packet log line for inference

    Args:
        packet_line: A line from listen_packets.py output

    Returns:
        Dictionary with extracted features
    """
    features = {}

    # Extract SNR
    import re
    snr_match = re.search(r'SNR:([-\d.]+)', packet_line)
    if snr_match:
        features['snr'] = float(snr_match.group(1))

    # Extract RSSI
    rssi_match = re.search(r'RSSI:([-\d.]+)', packet_line)
    if rssi_match:
        features['rssi'] = float(rssi_match.group(1))

    # Extract port
    port_match = re.search(r'Port:([^|]+)', packet_line)
    if port_match:
        features['port'] = port_match.group(1).strip()

    # Extract payload size
    payload_match = re.search(r'PayloadSize:(\d+)', packet_line)
    if payload_match:
        features['payload_size'] = int(payload_match.group(1))

    # Extract position if available
    lat_match = re.search(r'Lat:([-\d.]+)', packet_line)
    lon_match = re.search(r'Lon:([-\d.]+)', packet_line)
    if lat_match and lon_match:
        features['latitude'] = float(lat_match.group(1))
        features['longitude'] = float(lon_match.group(1))

    return features


# Example usage
if __name__ == "__main__":
    # Example known nodes data (from display_nodes CSV)
    example_nodes = {
        '!9eecae9c': {
            'node_number': '123456789',
            'long_name': 'Node Alpha',
            'short_name': 'ALPHA',
            'user_id': '!9eecae9c',
            'last_heard': '2025-09-11 17:30:00',
            'snr': '-10.5',
            'latitude': '37.7749',
            'longitude': '-122.4194',
            'altitude': '100',
            'uptime': '2h 30m 15s'
        }
    }

    # Create inference engine
    inference = PacketSenderInference(example_nodes)

    # Example packet features
    packet_features = {
        'snr': -10.0,
        'rssi': -80,
        'latitude': 37.7750,
        'longitude': -122.4195,
        'port': 'TEXT_MESSAGE_APP',
        'payload_size': 25
    }

    # Run inference
    candidates = inference.infer_sender(packet_features)

    print("Potential senders:")
    for node_id, score, reason in candidates:
        node_name = example_nodes.get(node_id, {}).get('short_name', node_id)
        print(".3f")
