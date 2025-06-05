# entrypoint.py
import subprocess
import threading

def run_bot():
    subprocess.run(["python3", "Debo_registration.py"])

def run_web():
    subprocess.run(["gunicorn", "health_check_server:app", "--bind", "0.0.0.0:{}".format(os.environ.get("PORT", "8000"))])

if __name__ == "__main__":
    import os
    t1 = threading.Thread(target=run_bot)
    t2 = threading.Thread(target=run_web)

    t1.start()
    t2.start()

    t1.join()
    t2.join()
