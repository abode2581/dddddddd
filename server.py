from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import os, json, re, zipfile, io, shutil, mimetypes, urllib.parse
from email.parser import BytesParser
from email.policy import default
ROOT=os.path.dirname(os.path.abspath(__file__)); DATA=os.path.join(ROOT,'sites'); os.makedirs(DATA,exist_ok=True)
class Handler(BaseHTTPRequestHandler):
 def send(self,code,body,ctype='application/json; charset=utf-8'):
  if isinstance(body,str): body=body.encode()
  self.send_response(code); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(body))); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(body)
 def do_GET(self):
  p=urllib.parse.urlparse(self.path).path
  if p=='/': return self.send(200,open(os.path.join(ROOT,'index.html'),'rb').read(),'text/html; charset=utf-8')
  if p=='/api/sites':
   sites=[x for x in os.listdir(DATA) if os.path.isdir(os.path.join(DATA,x))]; return self.send(200,json.dumps(sorted(sites,reverse=True)))
  if p.startswith('/sites/'):
   parts=p.split('/'); name=parts[2] if len(parts)>2 else ''; rel='/'.join(parts[3:]) or 'index.html'
   base=os.path.realpath(os.path.join(DATA,name)); path=os.path.realpath(os.path.join(base,urllib.parse.unquote(rel)))
   if not re.fullmatch(r'[a-z0-9-]{3,40}',name) or not path.startswith(base+os.sep) or not os.path.isfile(path): return self.send(404,'Not found','text/plain')
   return self.send(200,open(path,'rb').read(),mimetypes.guess_type(path)[0] or 'application/octet-stream')
  self.send(404,'Not found','text/plain')
 def do_POST(self):
  if self.path!='/api/upload': return self.send(404,'Not found')
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n>20*1024*1024: raise ValueError('حجم الملف أكبر من 20 ميغابايت')
   raw=self.rfile.read(n)
   form=BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers.get('Content-Type','')+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
   fields={part.get_param('name',header='content-disposition'):part for part in form.iter_parts()}
   name=fields['name'].get_payload(decode=True).decode().strip().lower() if 'name' in fields else ''; f=fields.get('file')
   if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]',name): raise ValueError('استخدم 3 إلى 40 حرفاً إنجليزياً أو رقماً أو شرطة للاسم')
   if not f or not f.get_filename(): raise ValueError('اختر ملف الموقع')
   target=os.path.join(DATA,name)
   if os.path.exists(target): raise ValueError('هذا الاسم مستخدم، اختر اسماً آخر')
   data=f.get_payload(decode=True); filename=f.get_filename().lower(); os.makedirs(target)
   try:
    if filename.endswith('.zip'):
     with zipfile.ZipFile(io.BytesIO(data)) as z:
      if len(z.infolist())>500 or sum(i.file_size for i in z.infolist())>50*1024*1024: raise ValueError('ملف ZIP كبير جداً')
      for i in z.infolist():
       dest=os.path.realpath(os.path.join(target,i.filename))
       if not dest.startswith(os.path.realpath(target)+os.sep) or (i.external_attr >> 16) & 0o170000 == 0o120000: raise ValueError('ملف ZIP غير آمن')
      z.extractall(target)
    elif filename.endswith(('.html','.htm')): open(os.path.join(target,'index.html'),'wb').write(data)
    else: raise ValueError('ارفع ملف ZIP أو HTML فقط')
    if not os.path.isfile(os.path.join(target,'index.html')): raise ValueError('يجب أن يحتوي الملف على index.html في المجلد الرئيسي')
   except Exception: shutil.rmtree(target,ignore_errors=True); raise
   self.send(200,json.dumps({'url':'/sites/'+name+'/'}))
  except Exception as e: self.send(400,json.dumps({'error':str(e)},ensure_ascii=False))
ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()
