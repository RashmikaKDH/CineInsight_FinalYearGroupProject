"""Single-process local background queue; persisted status survives page reconnects."""
import hashlib
import json
import logging
import os
import secrets
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs
from flask import Blueprint, current_app, session, request, jsonify, abort
from services import db_service as db
from services.report_import import parse_report
try:
    from src.extractors.cache_lock import CrossProcessLock
except ImportError:
    from cache_lock import CrossProcessLock

automation=Blueprint('automation',__name__)
ROOT=Path(__file__).resolve().parents[1]
EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix='cineinsight')
LOCK=threading.Lock()
PROCESS=secrets.token_hex(16)
ACTIVE=set()
log=logging.getLogger(__name__)
TERMINAL={'completed','partial','failed','interrupted'}
_WORKER_LOCK=None

def owner_dir(instance,user_id):
    return Path(instance)/'analysis_runs'/hashlib.sha256(str(user_id).encode()).hexdigest()

def analysis_lock_path(instance,user_id,aid):
    return owner_dir(instance,user_id)/str(aid)/'.task.lock'

def get_analysis_lock(instance,user_id,aid,timeout=0):
    return CrossProcessLock(analysis_lock_path(instance,user_id,aid),timeout=timeout)

def worker_lock_path(instance,process_token):
    return Path(instance)/'analysis_runs'/f'.worker_{process_token}.lock'

def get_worker_lock(instance,process_token,timeout=0):
    return CrossProcessLock(worker_lock_path(instance,process_token),timeout=timeout)

def release_worker_lock():
    global _WORKER_LOCK
    if _WORKER_LOCK is not None:
        try:
            _WORKER_LOCK.release()
        except Exception:
            pass
        _WORKER_LOCK = None

def ensure_worker_lock(instance):
    global _WORKER_LOCK
    target_path = worker_lock_path(instance, PROCESS)
    if _WORKER_LOCK is not None:
        if _WORKER_LOCK.lock_path == target_path and _WORKER_LOCK.is_locked():
            return _WORKER_LOCK
        release_worker_lock()
    lock=get_worker_lock(instance,PROCESS,timeout=0)
    try:
        lock.acquire(timeout=0)
        _WORKER_LOCK=lock
    except Exception:
        pass
    return _WORKER_LOCK

def is_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                STILL_ACTIVE = 259
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError, ProcessLookupError):
        return False

def is_worker_alive(instance, process_token: str | None, pid: int | None = None) -> bool:
    """Check if the worker process that registered process_token/pid is currently running."""
    if not process_token:
        return is_pid_alive(pid) if pid else False
    if process_token == PROCESS:
        return True
    wlock = get_worker_lock(instance, process_token, timeout=0)
    if wlock.is_locked():
        return True
    if pid and is_pid_alive(pid):
        return True
    return False

def is_analysis_active(instance,user_id,aid,check_lock=True):
    with LOCK:
        if (user_id,aid) in ACTIVE:
            return True
    if check_lock:
        lock=get_analysis_lock(instance,user_id,aid,timeout=0)
        if lock.is_locked():
            return True
    task_file=owner_dir(instance,user_id)/str(aid)/'task.json'
    if task_file.is_file():
        try:
            data=json.loads(task_file.read_text(encoding='utf-8'))
            if data.get('status') in ('queued','running'):
                proc = data.get('process')
                pid = data.get('pid')
                if is_worker_alive(instance, proc, pid):
                    return True
                # Worker is dead; queued/running task is stale
                return False
        except Exception:
            pass
    return False

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(path)

def valid_url(value):
    parsed=urlparse(value)
    if parsed.scheme not in ('http','https') or parsed.hostname not in ('youtube.com','www.youtube.com','m.youtube.com','youtu.be','www.youtu.be'):
        return False
    return bool(parsed.path.strip('/')) if parsed.hostname.endswith('youtu.be') else parsed.path=='/watch' and bool(parse_qs(parsed.query).get('v'))

def load_state(instance,user_id,aid):
    path=owner_dir(instance,user_id)/str(aid)/'task.json'
    if not path.is_file():return None
    with LOCK:
        state=json.loads(path.read_text(encoding='utf-8'))
        if state['status'] not in TERMINAL:
            proc=state.get('process')
            pid=state.get('pid')
            if not is_worker_alive(instance, proc, pid):
                state.update(status='interrupted',message='The server restarted before completion. Prepared files have been kept. Start a new analysis to try again.')
                write_json(path,state)
    return state

def public_state(state):
    fields=('analysis_id','status','stage','message','result_url','download_url','db_saved')
    return {k:state[k] for k in fields if k in state}

def enqueue(instance,user_id,url,request_id):
    folder=owner_dir(instance,user_id)
    request_key=hashlib.sha256(request_id.encode()).hexdigest()
    marker=folder/'requests'/(request_key+'.json')
    ensure_worker_lock(instance)
    with LOCK:
        if marker.exists():
            saved=json.loads(marker.read_text(encoding='utf-8'))
            if saved['url']!=url:raise ValueError('Request identifier already used for another video.')
            return saved['analysis_id']
        aid=db.create_pending_analysis(user_id,url)
        state={'analysis_id':aid,'user_id':user_id,'url':url,'status':'queued','stage':'queued',
               'message':'Waiting for local processing.','process':PROCESS,'pid':os.getpid()}
        write_json(folder/str(aid)/'task.json',state)
        write_json(marker,{'analysis_id':aid,'url':url})
        ACTIVE.add((user_id,aid))
        try:EXECUTOR.submit(process_analysis,instance,user_id,aid)
        except Exception:
            ACTIVE.discard((user_id,aid))
            state.update(status='failed',message='Unable to start processing.');write_json(folder/str(aid)/'task.json',state)
            raise
    return aid

def process_analysis(instance,user_id,aid):
    work=owner_dir(instance,user_id)/str(aid);path=work/'task.json'
    file_lock=get_analysis_lock(instance,user_id,aid,timeout=5)
    try:
        file_lock.acquire()
    except Exception:
        log.exception('Could not acquire cross-process lock for analysis %s',aid)
        with LOCK:
            ACTIVE.discard((user_id,aid))
        return
    try:
        state=json.loads(path.read_text(encoding='utf-8'));stage='preparation';final_csv=None
        def progress(message):
            # Callback receives stage/segment counters only, never credential/API error detail.
            with LOCK:
                state.update(status='running',stage=stage,message=message);write_json(path,state)
        try:
            from main import process_youtube_review_generator
            from src import local_inference as inference
            inference.reasoning_config(enabled=True)  # fail early, before download/Whisper
            db.update_analysis_state(user_id,aid,'running')
            prepared=None
            for event in process_youtube_review_generator(state['url'],work_dir=work/'prepared'):
                data=json.loads(event)
                if data['status']=='error':raise RuntimeError('Preparation failed.')
                if data['status']=='completed':prepared=data
                elif data['status'] not in ('aspect_error',):progress(data.get('message','Preparing review…'))
            if not prepared or not prepared.get('csv_path'):raise RuntimeError('Preparation did not produce input files.')
            stage='inference'
            args=SimpleNamespace(csv=prepared['csv_path'],video=prepared['video_path'],audio=prepared['audio_path'],
                model=str(ROOT/'models/cineinsight/cineinsight_crossmodal_attention_best.pth'),
                background=str(ROOT/'models/cineinsight/shap_background.npy'),background_meta=str(ROOT/'models/cineinsight/shap_background.json'),
                output=str(work/'inference'),device='auto',gemini_model=None,skip_gemini=False,progress_callback=progress)
            exit_code=inference.run(args)
            runs=list((work/'inference').glob('inference_*'))
            if len(runs)!=1:raise RuntimeError('Unexpected inference output folder.')
            final_csv=runs[0]/'cineinsight_final_explainability_report.csv'
            if not final_csv.is_file():raise RuntimeError('Final CSV was not saved.')
            raw=final_csv.read_bytes();summary=parse_report(raw)
            target_state='partial' if exit_code==2 else 'completed'
            if exit_code not in (0,2):raise RuntimeError('Inference did not complete.')
            stage='saving_results';progress('Saving your results…')
            report_id=hashlib.sha256(str(aid).encode()+b'\0'+raw).hexdigest()
            reports=Path(instance)/'imported_reports'/hashlib.sha256(str(user_id).encode()).hexdigest()
            reports.mkdir(parents=True,exist_ok=True)
            summary.update(title=state['url'],id=report_id,analysis_id=aid,video_url=state['url'],analysis_date='',pipeline_status=target_state)
            (reports/(report_id+'.csv')).write_bytes(raw)
            write_json(reports/(report_id+'.json'),summary)
            try:
                db.save_final_analysis(user_id,aid,summary,report_id,target_state)
                db_saved=True
            except Exception:
                log.exception('Final database save failed for analysis %s',aid)
                db_saved=False;target_state='partial'
                summary.update(pipeline_status='partial',database_save_warning=True)
                write_json(reports/(report_id+'.json'),summary)
            with LOCK:
                state.update(status=target_state,stage='finished',message='Results ready.' if target_state=='completed' else 'Results available; some explanations or database saving did not complete.',
                    db_saved=db_saved,result_url='/reports/'+report_id,download_url='/reports/'+report_id+'/download')
                write_json(path,state)
        except Exception:
            log.exception('Analysis %s failed during %s',aid,stage)
            # Recover saved predictions/SHAP for Gemini or later-stage errors when possible.
            with LOCK:
                state.update(status='failed',stage=stage,message='Analysis could not be completed. Earlier files are preserved. Check the local server log for details.')
                write_json(path,state)
            try:db.update_analysis_state(user_id,aid,'failed')
            except Exception:log.exception('Could not record failed status for %s',aid)
        finally:
            with LOCK:ACTIVE.discard((user_id,aid))
    finally:
        try:
            file_lock.release()
        except Exception:
            pass

@automation.route('/api/analyze/start',methods=['POST'])
def start():
    if 'user_id' not in session:return jsonify(error='Sign in to analyze a video.'),401
    body=request.get_json(silent=True) or {}
    if not secrets.compare_digest(str(body.get('token','')),str(session.get('analysis_token','missing'))):abort(400)
    url=body.get('url','');rid=body.get('request_id','')
    if not isinstance(url,str) or len(url)>1000 or not valid_url(url):return jsonify(error='Select a valid YouTube video URL.'),400
    if not isinstance(rid,str) or not 16<=len(rid)<=100:return jsonify(error='Invalid request identifier.'),400
    try:aid=enqueue(current_app.instance_path,session['user_id'],url,rid)
    except ValueError as exc:return jsonify(error=str(exc)),400
    except Exception:
        current_app.logger.exception('Could not queue analysis')
        return jsonify(error='Unable to save analysis history. Please check the database and try again.'),503
    return jsonify(analysis_id=aid,status_url='/api/analyze/status/'+str(aid)),202

@automation.route('/api/analyze/status/<int:aid>')
def status(aid):
    if 'user_id' not in session:return jsonify(error='Sign in to view progress.'),401
    state=load_state(current_app.instance_path,session['user_id'],aid)
    if not state:abort(404)
    return jsonify(public_state(state))
