import socket
import struct

multicast_group = '224.1.1.1'
server_address = ('', 10000)

# Erstelle ein UDP Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(server_address)

# Multicast-Gruppe beitreten
group = socket.inet_aton(multicast_group)
mreq = struct.pack('4sL', group, socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

print("Warte auf Nachrichten...")

# Nachrichten empfangen
while True:
    data, address = sock.recvfrom(1024)
    print(f'Empfangen: {data} von {address}')
