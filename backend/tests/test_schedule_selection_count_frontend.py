import subprocess
from pathlib import Path


def test_schedule_selection_count_tracks_checked_eligible_rows_and_partial_state():
    program=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1]+'/assets/app.js','utf8');
const code=source.slice(source.indexOf('  function updateScheduleSelectionCount('),source.indexOf('  function scheduleTaskCheckbox('));
const checks=[{checked:false,disabled:false},{checked:false,disabled:false},{checked:true,disabled:true}];
const count={},all={};const context={document:{querySelectorAll:()=>checks,getElementById:id=>id==='scheduleSelectedCount'?count:all}};vm.createContext(context);vm.runInContext(code,context);
context.updateScheduleSelectionCount();assert.equal(count.textContent,'已选 0 条');assert.equal(all.checked,false);
checks[0].checked=true;context.updateScheduleSelectionCount();assert.equal(count.textContent,'已选 1 条');assert.equal(all.indeterminate,true);
checks[1].checked=true;context.updateScheduleSelectionCount();assert.equal(count.textContent,'已选 2 条');assert.equal(all.checked,true);assert.equal(all.indeterminate,false);
checks[0].checked=checks[1].checked=false;context.updateScheduleSelectionCount();assert.equal(count.textContent,'已选 0 条');assert.equal(all.indeterminate,false);
assert.match(source,/id="scheduleSelectedCount" role="status"/);
assert.match(source,/event.target.matches\(".schedule-task-check"\)\) updateScheduleSelectionCount/);
'''
    result=subprocess.run(['node','-e',program,str(Path(__file__).resolve().parents[2])],text=True,capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr
