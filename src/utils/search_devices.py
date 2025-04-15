import platform
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

def ping_device(ip_address):
    """
    Ping the given IP address.
    If the device responds, return a tuple of (IP, hostname).
    Otherwise, return None.
    """
    # Determine parameter for ping command depending on OS
    count_param = "-n" if platform.system().lower() == "windows" else "-c"
    # Depending on the OS, you may need to modify the timeout parameter:
    # Windows uses '-w' (in milliseconds), Linux uses '-W' (in seconds).
    timeout_param = "-w" if platform.system().lower() == "windows" else "-W"
    
    try:
        # Send only 1 ICMP packet and wait briefly for a response
        command = ["ping", count_param, "1", timeout_param, "1", ip_address]
        subprocess.check_output(command, stderr=subprocess.DEVNULL)
        
        # If ping succeeds, attempt to resolve the hostname
        try:
            hostname = socket.gethostbyaddr(ip_address)[0]
        except socket.herror:
            # If unable to resolve the hostname, set as "Unknown"
            hostname = "Unknown"
        
        return (ip_address, hostname)
    except subprocess.CalledProcessError:
        # Ping failed
        return None

def main():
    # Define the subnet you wish to scan - adjust as needed
    network_prefix = "10.50.100."
    
    # Generate the list of IPs (e.g. from 1 to 254)
    ip_addresses = [f"{network_prefix}{i}" for i in range(1, 255)]
    
    alive_devices = []
    
    # Create a ThreadPoolExecutor with a certain number of workers
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Map the ping_device function onto the list of IPs
        results = executor.map(ping_device, ip_addresses)
        
        # Collect results
        for result in results:
            if result is not None:
                alive_devices.append(result)
    
    # Print the alive devices
    print("Devices responding to ping:")
    for ip, hostname in alive_devices:
        print(f"IP: {ip} - Hostname: {hostname}")

if __name__ == "__main__":
    main()
