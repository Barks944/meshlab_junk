import argparse
from meshtastic_node_display import MeshtasticNodeDisplay

def main():
    parser = argparse.ArgumentParser(
        description="Display nodes seen by Meshtastic device",
        epilog="Example: python display_nodes.py 192.168.86.39 --csv nodes.csv"
    )
    parser.add_argument("ip", help="The IP address of the device")
    parser.add_argument("--csv", help="Optional: Path to CSV file to save node information")
    args = parser.parse_args()

    displayer = MeshtasticNodeDisplay(args.ip)
    if displayer.connect():
        displayer.display_nodes(csv_path=args.csv)
        displayer.close()
    else:
        print("Failed to connect to the device.")

if __name__ == "__main__":
    main()
