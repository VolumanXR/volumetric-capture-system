import socket
import ipaddress
import subprocess
import re

def get_ip_address_in_network(target_network="10.50.100.0/24"):
    """
    Gibt die aktuelle IP-Adresse des Hosts zurück, die Teil des angegebenen Netzwerks ist.
    
    :param target_network: Das Zielnetzwerk im CIDR-Format. Standardmäßig "10.50.100.0/24".
    :return: Die IP-Adresse als String oder None, wenn keine passende IP gefunden wurde.
    """
    try:
        # Versuche, die IP über eine Socket-Verbindung zu ermitteln
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Verbinde zu einem externen Server (hier Google DNS)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        
        # Prüfe, ob die IP im Zielnetzwerk liegt
        if ipaddress.ip_address(ip) in ipaddress.ip_network(target_network):
            return ip
    except Exception:
        pass
    
    # Fallback: Verwende 'ipconfig' und parse die Ausgabe
    try:
        output = subprocess.check_output("ipconfig", encoding='utf-8')
        # Suche nach IPv4-Adressen
        ipv4_addresses = re.findall(r'IPv4-Adresse[.\s]*: ([\d.]+)', output)
        for ip in ipv4_addresses:
            if ipaddress.ip_address(ip) in ipaddress.ip_network(target_network):
                return ip
    except Exception as e:
        print(f"Fehler beim Abrufen der IP-Adresse: {e}")
    
    return None

if __name__ == "__main__":
    current_ip = get_ip_address_in_network()
    if current_ip:
        print(f"Die aktuelle IP-Adresse im Netzwerk 10.50.100.x ist: {current_ip}")
    else:
        print("Keine IP-Adresse im Netzwerk 10.50.100.x gefunden.")