import requests
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_haiku():
    try:
        # Connect to local LMStudio server (assuming default port 1234)
        url = "http://localhost:1234/v1/chat/completions"
        payload = {
            "model": "openai/gpt-oss-20b",  # Adjust if your model has a specific name
            "messages": [
                {"role": "user", "content": "Generate a short 5-word haiku about the Forest of Dean. Consider topics like wild boar, ale, caving, coal, iron ore, steam trains, local places like aylburton or lydney, cinderford or coleford."}
            ],
            "temperature": 1.5
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        haiku = response.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"Generated haiku: {haiku}")
        return haiku
    except Exception as e:
        logger.error(f"Failed to generate haiku: {str(e)}")
        return None

def send_haiku(haiku):
    try:
        # Call send_channel_message.py
        result = subprocess.run([
            "python", "send_channel_message.py", "192.168.86.39", "2", f'{haiku}'
        ], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Haiku sent successfully")
        else:
            logger.error(f"Failed to send haiku: {result.stderr}")
    except Exception as e:
        logger.error(f"Error sending haiku: {str(e)}")

if __name__ == "__main__":
    haiku = generate_haiku()
    if haiku:
        send_haiku(haiku)
    else:
        logger.error("No haiku generated, skipping send.")
