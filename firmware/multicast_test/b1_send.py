import socket

# Netzwerk-Broadcast-Adresse und Port festlegen
broadcast_address = '255.255.255.255'
port = 50000
message = b'Hallo, Broadcast!'

# Erstelle ein UDP-Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

# Nachricht an die Broadcast-Adresse senden
sock.sendto(message, (broadcast_address, port))
print(f'Nachricht gesendet: {message.decode()} an {broadcast_address}:{port}')
