"""Audit-only host-access bridge; service containers retain internal-only networking."""
import os,select,socket,socketserver
class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection((os.environ['TARGET_HOST'],int(os.environ.get('TARGET_PORT','8080')))) as upstream:
            sockets=[self.request,upstream]
            while True:
                ready,_,_=select.select(sockets,[],[],30)
                if not ready:return
                for source in ready:
                    data=source.recv(65536)
                    if not data:return
                    (upstream if source is self.request else self.request).sendall(data)
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
Server(('0.0.0.0',8000),Handler).serve_forever()
