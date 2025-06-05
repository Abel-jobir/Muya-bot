import subprocess
import threading
import os
import logging
import time
import psutil
import traceback

# Setup logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("log.txt"),
        logging.StreamHandler()
    ]
)

def monitor_system():
    """Log memory and CPU usage every 10s"""
    try:
        while True:
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent()
            logging.info(f"[MONITOR] RAM used: {mem.percent}%, CPU: {cpu}%")
            time.sleep(10)
    except Exception as e:
        logging.error("[MONITOR ERROR] " + str(e))
        traceback.print_exc()

def run_bot():
    try:
        logging.info("[BOT] Starting Debo_registration.py")
        subprocess.run(["python3", "Debo_registration.py"], check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"[BOT ERROR] Process failed: {e}")
    except Exception as e:
        logging.error("[BOT EXCEPTION] " + str(e))
        traceback.print_exc()

def run_web():
    try:
        port = os.environ.get("PORT", "8000")
        logging.info(f"[WEB] Starting Flask health check on port {port}")
        subprocess.run(["gunicorn", "health_check_server:app", "--bind", f"0.0.0.0:{port}"], check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"[WEB ERROR] Process failed: {e}")
    except Exception as e:
        logging.error("[WEB EXCEPTION] " + str(e))
        traceback.print_exc()

if __name__ == "__main__":
    logging.info("[MAIN] Starting entrypoint")
    threading.Thread(target=monitor_system, daemon=True).start()

    t1 = threading.Thread(target=run_bot)
    t2 = threading.Thread(target=run_web)

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    logging.info("[MAIN] Both threads finished — this usually means crash or shutdown.")
