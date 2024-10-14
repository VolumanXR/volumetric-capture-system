import socket

multicast_group = '224.1.1.1'
port = 10000
message = b'Hallo, Multicast!'

# Erstelle ein UDP Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Sende Nachricht an Multicast-Gruppe
sock.sendto(message, (multicast_group, port))
