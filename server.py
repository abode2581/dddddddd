from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from email.parser import BytesParser
from email.policy import default
import os,json,re,zipfile,io,shutil,mimetypes,urllib.parse,sqlite3,secrets,hmac,time,hashlib
ROOT=os.path.dirname(os.path.abspath(__file__)); DATA=os.environ.get('NOVA_DATA_DIR',os.path.join(ROOT,'sites')); os.makedirs(DATA,exist_ok=True)
DB=os.path.join(DATA,'nova.db'); sessions={}
def db():
 c=sqlite3.connect(DB); c.execute('CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, plan TEXT, note TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT "جديد")'); return c
with db(): pass
class Handler(BaseHTTPRequestHandler):
 def send(self,code,body,ctype='application/json; charset=utf-8',headers=None):
  if not isinstance(body,(str,bytes)): body=json.dumps(body,ensure_ascii=False)
  if isinstance(body,str): body=body.encode()
  self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
  for k,v in (headers or {}).items(): self.send_header(k,v)
  self.end_headers();self.wfile.write(body)
 def auth(self):
  cookie=self.headers.get('Cookie',''); token=next((x.strip()[5:] for x in cookie.split(';') if x.strip().startswith('nova=')),''); exp=sessions.get(token,0); return bool(exp>time.time())
 def readjson(self):
  n=int(self.headers.get('Content-Length','0'))
  if n>10000: raise ValueError('البيانات كبيرة جداً')
  return json.loads(self.rfile.read(n))
 def do_GET(self):
  p=urllib.parse.urlparse(self.path).path
  if p in ('/','/admin'): return self.send(200,open(os.path.join(ROOT,'admin.html' if p=='/admin' else 'index.html'),'rb').read(),'text/html; charset=utf-8')
  if p=='/api/orders':
   if not self.auth(): return self.send(401,{'error':'يرجى تسجيل الدخول'})
   with db() as c: rows=c.execute('SELECT id,name,phone,plan,note,created,status FROM orders ORDER BY id DESC LIMIT 500').fetchall()
   return self.send(200,{'orders':[dict(zip(('id','name','phone','plan','note','created','status'),r)) for r in rows]})
  if p=='/api/sites':
   if not self.auth(): return self.send(401,{'error':'يرجى تسجيل الدخول'})
   return self.send(200,[x for x in os.listdir(DATA) if os.path.isdir(os.path.join(DATA,x))])
  if p.startswith('/sites/'):
   parts=p.split('/'); name=parts[2] if len(parts)>2 else ''; rel='/'.join(parts[3:]) or 'index.html';base=os.path.realpath(os.path.join(DATA,name));path=os.path.realpath(os.path.join(base,urllib.parse.unquote(rel)))
   if not re.fullmatch(r'[a-z0-9-]{3,40}',name) or not path.startswith(base+os.sep) or not os.path.isfile(path): return self.send(404,'Not found','text/plain')
   return self.send(200,open(path,'rb').read(),mimetypes.guess_type(path)[0] or 'application/octet-stream')
  self.send(404,'Not found','text/plain')
 def do_POST(self):
  try:
   if self.path=='/api/login':
    v=self.readjson(); password=os.environ.get('ADMIN_PASSWORD',''); username=os.environ.get('ADMIN_USERNAME','admin')
    if len(password)<12: return self.send(503,{'error':'اضبط ADMIN_PASSWORD في Railway على كلمة سر لا تقل عن 12 حرفاً.'})
    if not hmac.compare_digest(str(v.get('username','')),username) or not hmac.compare_digest(str(v.get('password','')),password): return self.send(401,{'error':'اسم المستخدم أو كلمة المرور غير صحيح'})
    token=secrets.token_urlsafe(32); sessions[token]=time.time()+8*3600
    return self.send(200,{'ok':True},headers={'Set-Cookie':f'nova={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=28800'})
   if self.path=='/api/logout': return self.send(200,{'ok':True},headers={'Set-Cookie':'nova=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0'})
   if self.path=='/api/order':
    v=self.readjson(); name=str(v.get('name','')).strip()[:100]; phone=str(v.get('phone','')).strip()[:50]; plan=str(v.get('plan','')).strip(); note=str(v.get('note','')).strip()[:1000]
    if len(name)<2 or len(phone)<5 or plan not in ('البداية','النمو','الأعمال'): raise ValueError('يرجى إكمال الاسم ورقم التواصل واختيار الباقة')
    with db() as c: c.execute('INSERT INTO orders(name,phone,plan,note) VALUES(?,?,?,?)',(name,phone,plan,note))
    return self.send(200,{'ok':True})
   if self.path=='/api/status':
    if not self.auth(): return self.send(401,{'error':'يرجى تسجيل الدخول'})
    v=self.readjson(); status=v.get('status'); oid=int(v.get('id',0))
    if status not in ('جديد','قيد التواصل','مكتمل'): raise ValueError('حالة غير صالحة')
    with db() as c: c.execute('UPDATE orders SET status=? WHERE id=?',(status,oid))
    return self.send(200,{'ok':True})
   if self.path=='/api/upload':
    if not self.auth(): return self.send(401,{'error':'يجب تسجيل دخول الإدارة أولاً'})
    n=int(self.headers.get('Content-Length','0'))
    if n>20*1024*1024: raise ValueError('حجم الملف أكبر من 20 ميغابايت')
    form=BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers.get('Content-Type','')+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+self.rfile.read(n));fields={part.get_param('name',header='content-disposition'):part for part in form.iter_parts()}; name=fields['name'].get_payload(decode=True).decode().strip().lower() if 'name' in fields else ''; f=fields.get('file')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,38}[a-z0-9]',name): raise ValueError('استخدم من 3 إلى 40 حرفاً إنجليزياً أو رقماً أو شرطة')
    if not f or not f.get_filename(): raise ValueError('اختر ملف الموقع')
    target=os.path.join(DATA,name)
    if os.path.exists(target): raise ValueError('اسم الموقع مستخدم')
    data=f.get_payload(decode=True); filename=f.get_filename().lower();os.makedirs(target)
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
     if not os.path.isfile(os.path.join(target,'index.html')): raise ValueError('يجب وجود index.html في المجلد الرئيسي')
    except: shutil.rmtree(target,ignore_errors=True);raise
    return self.send(200,{'url':'/sites/'+name+'/'})
   self.send(404,{'error':'غير موجود'})
  except Exception as e: self.send(400,{'error':str(e) or 'حدث خطأ'})
ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT',8080))),Handler).serve_forever()
