"""Selected packages export complete text without copying UI truncation or changing progress."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_markdown_preserves_full_multilingual_content_and_grouping():
    script = r'''
const assert=require('node:assert/strict');
const {buildPackagesMarkdown}=require(process.argv[1]);
const long='完整说明\n'.repeat(250)+'```\n原文保留';
const item={package_id:'one',channel_id:'ch',channel_name:'泰语频道',chinese_title:'测试剧',business_drama_id:'DRM-01',youtube_video_id:'abc',package_version:2,production_date:'2026-11-07',planned_utc_time:'2026-11-07T10:00:00',channel_timezone:'Asia/Bangkok',titles:[{id:'t1',variant_number:1,localized_title:'🔥 หัวใจ',chinese_translation:'中文标题',core_phrase:'หัวใจ'}],covers:[{title_id:'t1',aspect_ratio:'16:9',creative_prompt:'封面提示词'}],description:{localized_text:long,chinese_translation:'中文说明'},playlist_id:'pl',playlists:[{id:'pl',local_name:'泰语列表',chinese_name:'中文列表'}],community_posts:[{sequence_number:1,planned_utc_time:'2026-11-07T12:00:00Z',localized_text:'社群原文',chinese_translation:'社群翻译',image_prompt:'社群图提示词'}]};
const before=JSON.stringify(item);
const md=buildPackagesMarkdown([item,{...item,package_id:'two',channel_id:'other',channel_name:'其他频道',chinese_title:'另一剧'}], '2026-11-07');
for(const value of [long,'🔥 หัวใจ','中文标题','封面提示词','中文说明','泰语列表','中文列表','社群原文','社群翻译','社群图提示词','DRM-01','https://www.youtube.com/watch?v=abc','2026-11-07 18:00','2026-11-07 17:00','本剧已选','运营包版本 V2']) assert(md.includes(value),value);
assert.equal((md.match(/^## 频道：/gm)||[]).length,2);
assert(md.includes('````text\n'+long+'\n````'));
assert.equal(JSON.stringify(item),before);
const minimal=buildPackagesMarkdown([{package_id:'empty',channel_name:'缺失频道',source_complete:false}], '2026-11-07');
assert(minimal.includes('数据不完整'));assert(minimal.includes('暂无'));assert(!minimal.includes('undefined'));
'''
    subprocess.run(['node', '-e', script, str(ROOT / 'assets/package-presentation.js')], check=True, capture_output=True, text=True)


def test_selection_filters_partial_state_and_downloads_only_checked_packages(tmp_path):
    source = (ROOT / 'assets/app.js').read_text()
    snippet = source[source.index('  function selectedPackageItems()'):source.index('  function packageProgressSummaryMarkup(')]
    script = r'''
const assert=require('node:assert/strict');
const state={date:'2026-11-07',packageSelectedIds:new Set(),packageItems:[{package_id:'one',chinese_title:'选中一'},{package_id:'two',chinese_title:'选中二'},{package_id:'three',chinese_title:'不选三'}]};
let visible=state.packageItems;
const filteredPackageItems=()=>visible, icon=()=>'';
const all={},count={},download={},clear={};
const el=id=>id==='packageSelectAll'?all:count;
const cards=state.packageItems.map(item=>({dataset:{selectionPackageId:item.package_id},classList:{toggle(){}},checkbox:{},querySelector(){return this.checkbox}}));
let downloaded='',blob;
const document={body:{appendChild(){}},createElement:()=>({click(){downloaded=this.download},remove(){}}),querySelectorAll:selector=>selector==='.package-selectable-card'?cards:[download,clear]};
const window={ZhijuPackagePresentation:require(process.argv[2])};
const URL={createObjectURL:value=>{blob=value;return 'blob:test'},revokeObjectURL(){}};
const setTimeout=callback=>callback(),notify=()=>{};
(async()=>{
 renderPackageSelection();assert.equal(download.disabled,true);
 const check=(value,checked)=>changePackageSelection({id:'',value,checked,classList:{contains:name=>name==='package-select-check'}});
 check('one',true);assert.equal(count.textContent,'已选 1 个');assert.equal(all.indeterminate,true);assert(!all.checked);
 visible=[state.packageItems[1]];
 changePackageSelection({id:'packageSelectAll',checked:true});assert.equal(count.textContent,'已选 2 个（当前筛选内 1 个）');assert(all.checked);
 downloadSelectedPackages();assert.equal(downloaded,'运营包_2026-11-07_2个.md');const md=await blob.text();assert(md.includes('选中一'));assert(md.includes('选中二'));assert(!md.includes('不选三'));
 changePackageSelection({id:'packageSelectAll',checked:false});assert.deepEqual([...state.packageSelectedIds],['one']);
 check('one',false);assert.equal(download.disabled,true);downloaded='';downloadSelectedPackages();assert.equal(downloaded,'');
 visible=[];renderPackageSelection();assert(all.disabled);assert(!all.checked);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    path = tmp_path / 'package-selection.cjs'
    path.write_text(script.replace('(async()=>{', snippet + '\n(async()=>{', 1))
    subprocess.run(['node', str(path), str(ROOT / 'assets/package-presentation.js')], check=True, capture_output=True, text=True)
