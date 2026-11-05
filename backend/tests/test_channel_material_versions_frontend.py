import subprocess
from pathlib import Path


def test_existing_material_is_shown_independently_of_unpublished_generation_rule():
    script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1]+'/assets/app.js','utf8');
const code=source.slice(source.indexOf('  function channelDetailBody('),source.indexOf('  let analysisRefreshTimer'));
const ctx={esc:x=>String(x??''),icon:()=>'',tag:x=>x,channelDetailTabs:()=>'',table:(headers,rows)=>rows.join('')};vm.createContext(ctx);vm.runInContext(code,ctx);
const html=ctx.channelDetailBody({channel:{id:'thai'},profile:{title_template:'🔥 A…B',fixed_symbol:'🔥',description:'泰语频道资料'},relevant_skills:[{name:'标题',code:'title',version_number:null}],branding_assets:[],keywords:[{keyword_type:'tag'}],playlists:[{status:'active'}],pinned_comment_templates:[{status:'active'}]},'versions');
assert.match(html,/泰语频道资料/);assert.match(html,/🔥 A…B/);assert.match(html,/已配置/);assert.match(html,/未发布规则/);assert.doesNotMatch(html,/>缺失</);assert.match(html,/生成规则（Skill）版本/);
'''
    result=subprocess.run(['node','-e',script,str(Path(__file__).resolve().parents[2])],text=True,capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr
