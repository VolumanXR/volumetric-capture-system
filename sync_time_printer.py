#!/usr/bin/env python3
import time
from datetime import datetime

def print_time_on_second_change():
    last_second = None
    try:
        while True:
            now = datetime.now()
            current_second = now.second
            if current_second != last_second:
                print(now.strftime('%Y-%m-%d %H:%M:%S'))
                last_second = current_second
            # Sleep a short time to prevent high CPU usage
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nTime printing stopped.")

if __name__ == "__main__":
    print("Starting synchronized time printer. Press Ctrl+C to stop.")
    print_time_on_second_change()
