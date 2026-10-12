"""Capture this knob's raw advertisements without changing its configuration."""
import argparse, ctypes, datetime, json, socket, struct, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knob_bridge"))
from mesh import reports
p=argparse.ArgumentParser(description=__doc__); p.add_argument('--seconds',type=int,default=90); a=p.parse_args()
s=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_RAW,socket.BTPROTO_HCI)
b=ctypes.create_string_buffer(struct.pack('=HHH',socket.AF_BLUETOOTH,65535,2)); libc=ctypes.CDLL(None,use_errno=True); libc.bind.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint]; libc.bind.restype=ctypes.c_int
if libc.bind(s.fileno(),b,6): raise OSError(ctypes.get_errno(),'HCI monitor bind failed')
s.settimeout(1); end=time.monotonic()+a.seconds; print('Capturing knob advertisements',flush=True)
while time.monotonic()<end:
 try: raw=s.recv(65535)
 except socket.timeout: continue
 if len(raw)<6: continue
 op,index,size=struct.unpack('<HHH',raw[:6])
 if op!=3 or index!=0 or len(raw)<size+6: continue
 for address,rssi,data in reports(raw[6:6+size]):
  if address.upper()=='F8:24:41:39:9F:38': print(json.dumps({'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'address':address,'rssi':rssi,'data':data.hex()}),flush=True)
s.close()
