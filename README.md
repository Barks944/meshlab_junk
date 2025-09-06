# Meshtastic Mesh Network Tools

A collection of Python scripts for interacting with Meshtastic devices over TCP, enabling easy message sending and packet listening in a mesh network environment.

## Features

- **Send Messages**: Send timestamped messages to specific channels on your Meshtastic device.
- **Listen for Packets**: Monitor incoming packets and messages from the mesh network.
- **Retry Logic**: Built-in retries for reliable communication.
- **Command-Line Interface**: Simple CLI for quick operations.

## Files

- `send_channel_message.py`: Script to send a single message to a Meshtastic channel with automatic timestamp prefix.
- `listen_packets.py`: Script to listen for incoming packets (details in script).
- `tests/`: Directory containing test files or configurations.

## Prerequisites

- Python 3.x
- Meshtastic library: `pip install meshtastic`
- A Meshtastic device configured for TCP connections (default port 4403)

## Usage

### Sending a Message

```bash
python send_channel_message.py <IP_ADDRESS> "<MESSAGE>"
```

Example:
```bash
python send_channel_message.py 192.168.86.39 "Hello Mesh!"
```

This will send: `6/9/25@1214 Hello Mesh!` (with current timestamp).

### Listening for Packets

```bash
python listen_packets.py --packets-only --filter-port 1 --show-text
```

(Refer to `listen_packets.py` for full options.)

## Configuration

- **IP Address**: Pass as first argument to `send_channel_message.py`.
- **Channel**: Hard-coded to index 1; modify `CHANNEL_INDEX` in the script if needed.
- **Retries**: Set to 3 attempts with 5-second delays; adjustable via `RETRY_COUNT` and `RETRY_DELAY`.

## Troubleshooting

- Ensure your Meshtastic device is online and accessible via TCP.
- Check firewall settings for port 4403.
- Use the Meshtastic CLI (`meshtastic --host <IP> --listen`) to verify connectivity.

## Contributing

Feel free to fork and improve! Open issues for bugs or feature requests.

## License

MIT License - Use at your own risk in mesh networks! 🚀
