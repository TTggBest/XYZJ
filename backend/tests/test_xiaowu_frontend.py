"""Exercise file selection, delayed preview, clipboard and export interactions."""
import subprocess
from pathlib import Path


def test_upload_feedback_preview_and_download(tmp_path):
    source = (Path(__file__).resolve().parents[2] / 'assets/app.js').read_text()
    snippet = source[source.index('  function showXiaowuSync()'):source.index('  const renderers =')]
    fixture = r'''
const assert=require('node:assert/strict');
const state={view:'xiaowuSync',xiaowuKind:'cid',xiaowuPreviews:{binding:null,cid:null},xiaowuFiles:{binding:[],cid:[]},xiaowuBusy:{binding:false,cid:false},xiaowuErrors:{binding:'',cid:''}};
const root={innerHTML:''};
const auth={capture:()=>1,isCurrent:()=>true};
let copied='',messages=[];
const copyText=async value=>{copied=value},notify=(...args)=>messages.push(args);
const icon=()=>'',renderIcons=()=>{};
const esc=value=>String(value).replaceAll('<','&lt;');
const table=(headers,rows)=>headers.join('|')+rows.join('');
class FormData {constructor(){this.files=[]}append(key,file){this.files.push(file)}}
let resolveUpload,rejectUpload,requestCount=0,lastPayload;
const api=async(path,options)=>{requestCount++;if(path.includes('/preview/')){lastPayload=options.body;return new Promise((resolve,reject)=>{resolveUpload=resolve;rejectUpload=reject})}return {blob:{}}};
let downloaded='';
const document={body:{appendChild(){}},createElement:()=>({click(){downloaded=this.download},remove(){}})};
const URL={createObjectURL:()=> 'blob:test',revokeObjectURL(){}};
const setTimeout=callback=>callback();
(async()=>{
 showXiaowuSync();assert(root.innerHTML.includes('multiple'));assert(root.innerHTML.includes('DM-2609LLJ153'));assert(root.innerHTML.includes('上海诣星智能科技有限公司'));
 for(const [label,value] of [['合同编号','DM-2609LLJ153'],['公司名称','上海诣星智能科技有限公司']]){
  await copyXiaowuValue({dataset:{label,value}});assert.equal(copied,value);assert.equal(messages.at(-1)[0],label+'已复制');
 }
 const one={name:'one.csv',size:1024},two={name:'two.csv',size:2048};
 selectXiaowuFiles([one]);selectXiaowuFiles([two]);assert.deepEqual(state.xiaowuFiles.cid,[one,two]);assert(root.innerHTML.includes('已选择 2 个文件'));
 selectXiaowuFiles([{name:'wrong.xlsx'}]);assert.equal(state.xiaowuFiles.cid.length,2);
 const pending=uploadXiaowu({});assert(state.xiaowuBusy.cid);assert(root.innerHTML.includes('正在读取文件并处理'));assert.deepEqual(lastPayload.files,[one,two]);
 await uploadXiaowu({});assert.equal(requestCount,1);
 selectXiaowuFiles([one]);assert.equal(state.xiaowuFiles.cid.length,2);
 resolveUpload({kind:'cid',headers:['授权方','视频链接'],file_count:2,total:2,issue_count:0,rows:[{file:'one.csv',line:2,values:['公司','https://youtube.com/a'],issues:[]}]});
 await pending;assert(!state.xiaowuBusy.cid);assert(root.innerHTML.includes('全部通过，可以下载'));
 const button={disabled:false,textContent:''};await downloadXiaowu(button);assert.equal(downloaded,'小五解CID汇总.xlsx');assert.equal(button.disabled,false);
 selectXiaowuFiles([one]);assert.equal(state.xiaowuPreviews.cid,null);
 const failing=uploadXiaowu({});rejectUpload(new Error('文件解析失败'));await failing;assert(!state.xiaowuBusy.cid);assert(root.innerHTML.includes('文件解析失败'));assert.equal(state.xiaowuFiles.cid.length,3);
 state.xiaowuKind='binding';showXiaowuSync();assert(root.innerHTML.includes('accept=".xlsx"'));assert(!root.innerHTML.includes(' multiple'));
 selectXiaowuFiles([{name:'a.xlsx',size:1},{name:'b.xlsx',size:1}]);assert.equal(state.xiaowuFiles.binding.length,0);
 selectXiaowuFiles([{name:'a.xlsx',size:1}]);assert.equal(state.xiaowuFiles.binding.length,1);
 state.xiaowuPreviews.binding={headers:['作品名称'],file_count:1,total:1,issue_count:1,rows:[{file:'a.xlsx',line:2,values:[''],issues:['未找到唯一对应剧名']}]};
 showXiaowuSync();assert(root.innerHTML.includes('暂不能导出'));assert(root.innerHTML.includes('未找到唯一对应剧名'));
 const before=requestCount;await downloadXiaowu(button);assert.equal(requestCount,before);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    script = tmp_path / 'xiaowu-ui.cjs'
    script.write_text(fixture.replace('(async()=>{', snippet + '\n(async()=>{', 1))
    subprocess.run(['node', str(script)], check=True, capture_output=True, text=True)
    assert 'if (form.id === "xiaowuUploadForm")' in source
    assert 'action === "xiaowu-export"' in source
