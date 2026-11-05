"""Exercise the upload/preview/download UI with a delayed API response."""
import subprocess
from pathlib import Path


def test_upload_feedback_preview_and_download(tmp_path):
    source=(Path(__file__).resolve().parents[2]/'assets/app.js').read_text()
    snippet=source[source.index('  function showXiaowuSync()'):source.index('  const renderers =')]
    fixture=r'''
const assert=require('node:assert/strict');
const state={view:'xiaowuSync',xiaowuKind:'cid',xiaowuPreviews:{binding:null,cid:null}};
const root={innerHTML:''},feedback={textContent:''},submit={disabled:false,textContent:''};
const auth={capture:()=>1,isCurrent:()=>true};
const el=()=>feedback,notify=()=>{};
const esc=value=>String(value).replaceAll('<','&lt;');
const table=(headers,rows)=>headers.join('|')+rows.join('');
const empty=(a,b)=>a+b;
class FormData {constructor(form){}}
let resolveUpload,requestCount=0;
const api=async(path,options)=>{requestCount++;if(path.includes('/preview/'))return new Promise(resolve=>{resolveUpload=resolve});return {blob:{}}};
let downloaded='';
const document={body:{appendChild(){}},createElement:()=>({click(){downloaded=this.download},remove(){}})};
const URL={createObjectURL:()=> 'blob:test',revokeObjectURL(){}};
const setTimeout=callback=>callback();
(async()=>{
  showXiaowuSync();assert(root.innerHTML.includes('multiple'));assert(root.innerHTML.includes('解 CID'));
  const form={dataset:{},querySelector:()=>submit};
  const pending=uploadXiaowu(form);
  assert(submit.disabled);assert(feedback.textContent.includes('正在读取文件'));
  await uploadXiaowu(form);assert.equal(requestCount,1);
  resolveUpload({kind:'cid',headers:['授权方','视频链接'],file_count:2,total:2,issue_count:0,rows:[{file:'one.csv',line:2,values:['公司','https://youtube.com/a'],issues:[]}]});
  await pending;
  assert(root.innerHTML.includes('共 2 条'));assert(root.innerHTML.includes('下载 Excel'));
  const button={disabled:false,textContent:''};await downloadXiaowu(button);
  assert.equal(downloaded,'小五解CID汇总.xlsx');assert.equal(button.disabled,false);
  state.xiaowuKind='binding';showXiaowuSync();assert(root.innerHTML.includes('accept=".xlsx"'));assert(!root.innerHTML.includes(' multiple'));
  state.xiaowuPreviews.binding={headers:['作品名称'],file_count:1,total:1,issue_count:1,rows:[{file:'a.xlsx',line:2,values:[''],issues:['未找到唯一对应剧名']}]};
  showXiaowuSync();assert(root.innerHTML.includes('暂不能导出'));assert(root.innerHTML.includes('未找到唯一对应剧名'));
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    script=tmp_path/'xiaowu-ui.cjs';script.write_text(fixture.replace('(async()=>{',snippet+'\n(async()=>{',1))
    subprocess.run(['node',str(script)],check=True,capture_output=True,text=True)
    assert 'if (form.id === "xiaowuUploadForm")' in source
    assert 'action === "xiaowu-export"' in source
