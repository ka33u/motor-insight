"""Manage one loopback-only local preview, with a distinct PID/log per port."""
import argparse,json,os,re,signal,socket,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def paths(port):
    suffix='' if port==8765 else '-'+str(port)
    return ROOT/f'data/server{suffix}.pid',ROOT/f'data/server{suffix}.log'

def healthy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/auth',timeout=1) as response:
            value=json.load(response)
            return isinstance(value,dict) and 'authenticated' in value and 'can_import' in value
    except Exception:return False

def description(pid):
    return subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout.strip()

def owned(pid,port):
    desc=description(pid)
    command=re.escape(str(ROOT/'manage.py'))+r'\s+runserver\s+127\.0\.0\.1:'+str(port)+r'\s+--noreload(?:\s|$)'
    return bool(desc and re.search(command,desc))

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['start','status','stop'],nargs='?',default='start')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args(argv);port=args.port
    if not 1024<=port<=65535:parser.error('port must be 1024–65535')
    pidfile,logfile=paths(port);url=f'http://127.0.0.1:{port}'
    pid=int(pidfile.read_text().strip()) if pidfile.exists() else None
    if pid is not None and pid<=0:raise RuntimeError('Invalid managed PID')
    if args.command=='stop':
        if pid is None:print('No managed preview PID');return
        desc=description(pid)
        if desc and not owned(pid,port):raise RuntimeError('PID belongs to another process; refusing to stop it')
        if desc:
            os.kill(pid,signal.SIGTERM)
            for _ in range(50):
                if not description(pid):break
                time.sleep(.1)
            else:raise RuntimeError('Process has not stopped; PID retained for inspection')
        pidfile.unlink();print('STOPPED '+url);return
    if (ROOT/'.restore-in-progress').exists():raise RuntimeError('Restore is incomplete; inspect .restore-in-progress and data/recovery-install.log')
    running=healthy(port)
    managed=pid is not None and owned(pid,port)
    if args.command=='status':
        print(('RUNNING '+url) if running and managed else ('PORT IN USE; not this managed preview' if running else 'STOPPED'))
        return
    if running:
        if not managed:raise RuntimeError('Port serves another/unmanaged application; choose another --port')
        print('RUNNING '+url+' PID '+str(pid));return
    if managed:raise RuntimeError('Managed process exists but is not healthy; inspect its log before restarting')
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Port is occupied; choose another --port')
    ROOT.joinpath('data').mkdir(exist_ok=True)
    env=os.environ.copy()
    for name in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','DJANGO_SETTINGS_MODULE','MOTOR_SQLITE_PATH'):env.pop(name,None)
    env['PYTHONNOUSERSITE']='1'
    with logfile.open('ab') as log:
        child=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'manage.py'),'runserver',f'127.0.0.1:{port}','--noreload'],
                               cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    pidfile.write_text(str(child.pid))
    for _ in range(100):
        if child.poll() is not None:raise RuntimeError('Preview failed; inspect '+str(logfile))
        if healthy(port):print('RUNNING '+url+' PID '+str(child.pid));return
        time.sleep(.1)
    raise RuntimeError('Preview not healthy yet; inspect '+str(logfile)+' before another start')

if __name__=='__main__':main()
