import csv
import os
import shutil

CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ip_config.csv')  # Path to your CSV file
SD_BOOT = "E:\\"  # Adjust to your mount path
SD_ROOT = "H:\\"  # Adjust to your mount path

def configure_sd_card(ip, hostname):
    # Configure hostname
    with open(os.path.join(SD_ROOT, "etc\\hostname"), "w") as f:
        f.write(hostname + "\n")
    
    with open(os.path.join(SD_ROOT, "etc\\hosts"), "w") as f:
        f.write("127.0.0.1 localhost\n")
        f.write(f"127.0.1.1 {hostname}\n")
    
    # Configure static IP
    dhcpcd_conf = os.path.join(SD_ROOT, "etc/dhcpcd.conf")
    with open(dhcpcd_conf, "a") as f:
        f.write(f"""
interface wlan0
static ip_address={ip}/24
static routers=10.50.100.1
static domain_name_servers=10.50.100.1
""")

def main():
    with open(CSV_FILE, "r") as file:
        reader = csv.reader(file)
        for row in reader:
            ip, hostname = row
            print(f"Configuring SD card for {hostname} ({ip})...")
            configure_sd_card(ip, hostname)
            input("Swap SD cards and press Enter to continue...")

if __name__ == "__main__":
    main()
