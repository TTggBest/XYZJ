"""Small local process record for probing a claimed job, without credentials."""
import json
import os
import time
from pathlib import Path
from threading import Lock


def process_alive(pid):
    if not pid:return False
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    except PermissionError:return True
    return True


class ExecutionState:
    def __init__(self,path,envelope):
        self.path=Path(path)
        self.lock=Lock()
        self.data={key:envelope[key] for key in ('run_id','work_order_id','claim_id')}
        self.data.update(worker_pid=os.getpid(),model_pid=None,finished=False,last_heartbeat=time.time())
        self.update()

    def update(self,**values):
        with self.lock:
            self.data.update(values)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.data))
            temporary.replace(self.path)
