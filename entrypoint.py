# entrypoint.py
import subprocess
import threading
import os

def run_bot():
    subprocess.run(["python3", "Debo_registration.py"])

def run_web():
    subprocess.run(["gunicorn", "health_check_server:app", "--bind", f"0.0.0.0:{os.environ.get('PORT', '8000')}"])

if __name__ == "__main__":
    t1 = threading.Thread(target=run_bot)
    t2 = threading.Thread(target=run_web)

    t1.start()
    t2.start()

    t1.join()
    t2.join()
