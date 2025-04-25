import platform
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

def ping_device(ip_address):
    count_param = "-n" if platform.system().lower() == "windows" else "-c"
    timeout_param = "-w" if platform.system().lower() == "windows" else "-W"
    
    try:
        command = ["ping", count_param, "1", timeout_param, "1", ip_address]
        subprocess.check_output(command, stderr=subprocess.DEVNULL)
        
        try:
            hostname = socket.gethostbyaddr(ip_address)[0]
        except socket.herror:
            hostname = "Unknown"
        
        return (ip_address, hostname)
    except subprocess.CalledProcessError:
        return None

def main():
    network_prefix = "10.50.100."
    ip_addresses = [f"{network_prefix}{i}" for i in range(1, 255)]
    alive_devices = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(ping_device, ip_addresses)
        for result in results:
            if result is not None:
                alive_devices.append(result)
    
    print("Devices responding to ping:")
    for ip, hostname in alive_devices:
        print(f"IP: {ip} - Hostname: {hostname}")

if __name__ == "__main__":
    main()
