# Meshtastic Mesh Network Tools

A collection of Python scripts for interacting with Meshtastic devices over TCP, enabling message sending, packet listening, and automated content generation in a mesh network environment.

## Features

- **Send Messages**: Send timestamped messages to specific channels with optional QueueStatus confirmation.
- **Repeat Messages**: Automatically repeat messages at specified intervals with sequence numbers for tracking.
- **Haiku Generation**: Generate AI-powered haiku poems about the Forest of Dean and send them to the mesh.
- **Packet Listening**: Monitor incoming packets with advanced filtering, logging, and reconnection capabilities.
- **Reliability**: Built-in retries, error handling, and firmware confirmation for message queuing.
- **Command-Line Interface**: Flexible CLI with multiple options for customization.

## Files

- `send_channel_message.py`: Send messages to Meshtastic channels with timestamp, optional repeat, sequence numbers, and QueueStatus confirmation.
- `generate_haiku_and_send.py`: Generate haiku using local AI (LMStudio) and send via `send_channel_message.py`.
- `listen_packets.py`: Listen for incoming packets with comprehensive filtering, logging, and display options.
- `README.md`: This documentation file.

## Prerequisites

- Python 3.x
- Meshtastic library: `pip install meshtastic`
- For haiku generation: [LMStudio](https://lmstudio.ai/) running locally on port 1234 with a compatible model (e.g., GPT-OSS-20B)
- A Meshtastic device configured for TCP connections (default port 4403)

## Usage

### Sending a Message (`send_channel_message.py`)

Send a single message or repeat messages with sequence numbers.

```bash
python send_channel_message.py <IP_ADDRESS> <CHANNEL> "<MESSAGE>" [OPTIONS]
```

**Arguments:**
- `IP_ADDRESS`: IP address of the Meshtastic device
- `CHANNEL`: Channel index (1-7, cannot be 0)
- `MESSAGE`: The message text to send

**Options:**
- `--repeat-every SECONDS`: Repeat the message every X seconds with incrementing sequence numbers (#0, #1, #2, ..., #999, then back to #0)
- `--no-wait`: Skip waiting for QueueStatus confirmation (faster but less reliable)

**Examples:**

Send a single message:
```bash
python send_channel_message.py 192.168.86.39 2 "Hello Mesh!"
```
Output: `9/7/25@1214 Hello Mesh!`

Send repeating messages with sequence numbers:
```bash
python send_channel_message.py 192.168.86.39 2 "Status update" --repeat-every 60
```
Output: `9/7/25@1214 #0 Status update`, `9/7/25@1215 #1 Status update`, etc.

Send without confirmation:
```bash
python send_channel_message.py 192.168.86.39 2 "Quick message" --no-wait
```

### Generating and Sending Haiku (`generate_haiku_and_send.py`)

Generate AI haiku about the Forest of Dean and send them to the mesh.

```bash
python generate_haiku_and_send.py <IP_ADDRESS> <CHANNEL> [OPTIONS]
```

**Arguments:**
- `IP_ADDRESS`: IP address of the Meshtastic device
- `CHANNEL`: Channel index (1-7, cannot be 0)

**Options:**
- `--repeat-every SECONDS`: Generate and send a new haiku every X seconds

**Examples:**

Send a single haiku:
```bash
python generate_haiku_and_send.py 192.168.86.39 2
```
Output: `9/7/25@1214 [AI-generated haiku about Forest of Dean]`

Send repeating haiku:
```bash
python generate_haiku_and_send.py 192.168.86.39 2 --repeat-every 3600
```
Output: `9/7/25@1214 #0 [AI-generated haiku]`, `9/7/25@1314 #1 [AI-generated haiku]`, etc.

### Listening for Packets (`listen_packets.py`)

Monitor incoming packets with advanced filtering and logging.

```bash
python listen_packets.py [OPTIONS]
```

**Key Options:**
- `--ip IP_ADDRESS`: Device IP (default: 192.168.86.39)
- `--filter-channel CHANNELS`: Filter by channel numbers
- `--filter-port PORTS`: Filter by port types (e.g., TEXT_MESSAGE_APP, TELEMETRY_APP)
- `--filter-node NODES`: Filter by node IDs or names
- `--show-text`: Display text message content
- `--packets-only`: Show only application layer packets
- `--log-file FILE`: Log packets to file
- `--quiet-sync`: Hide repetitive sync messages
- `--no-reconnect`: Disable auto-reconnection
- `--list-ports`: List known Meshtastic port types and exit

**Examples:**

Listen for text messages on channel 2:
```bash
python listen_packets.py --filter-channel 2 --filter-port TEXT_MESSAGE_APP --show-text
```

Log all packets to file:
```bash
python listen_packets.py --log-file packets.log --packets-only
```

List available port types:
```bash
python listen_packets.py --list-ports
```

## Configuration

- **IP Address**: Configurable per script (default: 192.168.86.39)
- **Channel**: Specified as argument (1-7)
- **Retries**: 3 attempts with 5-second delays (hardcoded in scripts)
- **QueueStatus Timeout**: 10 seconds for confirmation (in `send_channel_message.py`)
- **LMStudio**: Ensure running on localhost:1234 for haiku generation

## Troubleshooting

- Ensure your Meshtastic device is online and accessible via TCP on port 4403.
- Check firewall settings and network connectivity.
- For haiku generation, verify LMStudio is running with a compatible model.
- Use the Meshtastic CLI (`meshtastic --host <IP> --listen`) to verify device connectivity.
- If connection fails, check device configuration and TCP server settings.

## Contributing

Feel free to fork and improve! Open issues for bugs or feature requests.

## License

MIT License - Use at your own risk in mesh networks! 🚀
