from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from threading import Event
import json

class PlannerFakeReceiver:
    def __init__(self, status, body, headers=None, mode="NORMAL"):
        self.status,self.body,self.headers,self.requests,self.mode=status,body,headers if headers is not None else {"Content-Type":"application/json"},[],mode; self.request_received=Event(); self.release_response=Event(); self.errors=[]
    def __enter__(self):
        outer=self
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                raw=self.rfile.read(int(self.headers.get("Content-Length","0"))); outer.requests.append((self.command,self.path,{k:(k in self.headers) for k in ("Content-Type","X-SmartOffice-Issuer","X-SmartOffice-Secret","Idempotency-Key")},raw))
                outer.request_received.set()
                if outer.mode == "HOLD_BEFORE_RESPONSE": outer.release_response.wait(2); return
                if outer.mode == "CLOSE_BEFORE_RESPONSE": self.connection.close(); return
                self.send_response(outer.status)
                for k,v in outer.headers.items(): self.send_header(k,v)
                if outer.mode == "ABORT_RESPONSE_BODY": self.send_header("Content-Length", "1024")
                self.end_headers(); self.wfile.write(outer.body if isinstance(outer.body,bytes) else json.dumps(outer.body).encode())
                if outer.mode == "ABORT_RESPONSE_BODY": self.connection.close()
            def log_message(self,*_): pass
        self.server=ThreadingHTTPServer(("127.0.0.1",0),H); self.thread=Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); return self
    @property
    def url(self): return f"http://127.0.0.1:{self.server.server_port}/api/integrations/smartoffice/drafts"
    def __exit__(self,*_): self.server.shutdown();self.server.server_close();self.thread.join(2)
