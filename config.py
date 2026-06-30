import os

# Resolve the directory of the script to locate the .env file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")

# If a local .env file exists, load it into os.environ
if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip()
                        os.environ[key] = val
    except Exception as e:
        print(f"[ERROR] Failed to load .env file: {e}")
