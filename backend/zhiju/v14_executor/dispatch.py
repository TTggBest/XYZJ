"""A single local pool consumes the cloud's shared cross-module admission queue."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from pathlib import Path
from threading import Event
import json
import sys
import os
import signal
import time
from uuid import uuid4
from .execution_state import process_alive
from . import channel_analysis,schedule_planning
from .runner import run_once,replay_pending


def release_claim(client,root,run):
    folder=Path(root)/'executor-releases';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(run['claim_id']+'.json')
    body={'claim_id':run['claim_id']}
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(body));temporary.replace(path)
    client.transport_request('POST','/executor/releases',body)
    path.unlink(missing_ok=True)
    (Path(root)/'executor-active'/(run['claim_id']+'.json')).unlink(missing_ok=True)


def drain(client_factory,model_factory,config,root,workers=10,once=False):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    recovery=client_factory()
    # The intent is written before HTTP claim, so a lost reply or killed worker
    # cannot strand an admitted slot. Never reclaim while its CLI is still alive.
    active_root=root/'executor-active';active_root.mkdir(exist_ok=True)
    for path in active_root.glob('*.json'):
        record=json.loads(path.read_text())
        if process_alive(record['worker_pid']):continue
        pid=record.get('model_pid')
        if process_alive(pid):
            os.killpg(pid,signal.SIGTERM)
            deadline=time.monotonic()+5
            while process_alive(pid) and time.monotonic()<deadline:time.sleep(.1)
            if process_alive(pid):
                os.killpg(pid,signal.SIGKILL)
                deadline=time.monotonic()+5
                while process_alive(pid) and time.monotonic()<deadline:time.sleep(.1)
                if process_alive(pid):raise RuntimeError('旧 Codex 进程停止尚未确认，请检查执行器后重新唤起')
        release_claim(recovery,root,record)
    def replay_releases():
        for path in (root/'executor-releases').glob('*.json'):
            try:
                body=json.loads(path.read_text())
                recovery.transport_request('POST','/executor/releases',body)
                path.unlink(missing_ok=True)
                (active_root/(body['claim_id']+'.json')).unlink(missing_ok=True)
            except (ConnectionError,FileNotFoundError):continue
    replay_releases()
    recoveries=(lambda:channel_analysis.recover_cached(recovery,config,root/'channel-analysis'),
                lambda:schedule_planning.recover_cached(recovery,root/'channel-scheduling'),
                lambda:replay_pending(recovery,root))
    for recover in recoveries:
        try:recover()
        except PermissionError:raise
        except (ConnectionError,RuntimeError,OSError) as exc:print('待回传任务暂未恢复：'+str(exc),file=sys.stderr)
    stop=Event();pending=set()
    def process(item):
        client=client_factory();model=model_factory();run=item['run'];kind=item['task_type']
        active_path=active_root/(run['claim_id']+'.json')
        record={'claim_id':run['claim_id'],'worker_pid':os.getpid(),'model_pid':None}
        def process_changed(pid):
            record['model_pid']=pid
            temporary=active_path.with_suffix('.tmp');temporary.write_text(json.dumps(record));temporary.replace(active_path)
        model.process_changed=process_changed
        try:
            if kind=='operation_package':run_once(client,model,cache_root=root,recover=False,stop_event=stop,envelope=run)
            elif kind=='channel_analysis':channel_analysis.process_claimed(client,model,config,root/'channel-analysis',run,stop)
            else:schedule_planning.process_claimed(client,model,config,root/'channel-scheduling',run,stop)
        except PermissionError:stop.set();raise
        finally:
            # All model subprocesses have returned/stopped before the cloud may reuse this slot.
            release_claim(client,root,run)
            active_path.unlink(missing_ok=True)
    pool=ThreadPoolExecutor(max_workers=workers)
    try:
        while not stop.is_set():
            replay_releases()
            done={f for f in pending if f.done()}
            for future in done:
                pending.remove(future)
                try:future.result()
                except PermissionError:raise
                except (RuntimeError,ValueError,OSError) as exc:print('本任务执行异常，其他任务继续：'+str(exc),file=sys.stderr)
            empty=False
            while len(pending)<workers and not stop.is_set():
                claim_id=str(uuid4());intent=active_root/(claim_id+'.json')
                intent.write_text(json.dumps({'claim_id':claim_id,'worker_pid':os.getpid(),'model_pid':None}))
                item=client_factory().claim_any(claim_id=claim_id)
                if not item:intent.unlink();empty=True;break
                if item.get('waiting_for_capacity'):intent.unlink();break
                pending.add(pool.submit(process,item))
                if once:break
            if once:
                for future in pending:future.result()
                return
            if empty and not pending:return
            if pending:wait(pending,timeout=2,return_when=FIRST_COMPLETED)
            else:stop.wait(2)
        for future in pending:future.result()
    finally:
        stop.set();pool.shutdown(wait=True,cancel_futures=True)
