import socket

# Port definieren, auf dem Nachrichten empfangen werden sollen
port = 50000

# Erstelle ein UDP-Socket und binde es an alle verfügbaren Schnittstellen
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', port))

print(f'Warte auf Broadcast-Nachrichten auf Port {port}...')

# Nachricht empfangen
while True:
    data, address = sock.recvfrom(1024)
    print(f'Empfangen: {data.decode()} von {address}')
