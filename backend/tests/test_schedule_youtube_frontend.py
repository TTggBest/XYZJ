from test_auth_frontend_contract import run_node


def test_full_schedule_publication_column_distinguishes_scheduled_and_public_videos():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const cases=[['public',true,'public',false],['scheduled',true,'scheduled',true],
 ['private',true,'private',false],['incomplete',false,'scheduled',false],['missing',true,'unavailable',false]];
const rows=cases.map(([name,complete,state,published])=>({schedule_id:name,chinese_title:name+'-drama',
 source_video_id:name+'-video',is_uploaded:true,is_published:published,
 is_task_written:name==='public',task_id:name==='public'?'existing-task':null,task_status:'completed',
 planned_beijing_time:'2026-10-28T01:00:00',
 video_sync:{sync_complete:complete,selected:{state,video_id:name+'-video'},warnings:[]}}));
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"频道"}]');
 if(path.startsWith('/api/v3/schedules/channel-view'))return new Response(JSON.stringify({page:1,page_size:50,total:rows.length,items:rows,video_updated_at:'2026-10-29T08:00:00Z'}));
 return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(action,extra={}){
 const button={dataset:{action,...extra},closest:()=>null};
 await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
}
await click('go-schedules');
await click('schedule-view-mode',{mode:'full'});
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/视频最新更新时间：2026\/10\/29 16:00:00（北京时间）/);
assert.match(html,/<th[^>]*>发布状态<\/th>/);
assert.match(html,/<th[^>]*>任务生成<\/th>/);
const tableRows=html.match(/<tr>[\s\S]*?<\/tr>/g);
for(const [name,expected] of [['public','已上线'],['scheduled','已预约'],['private','未上线'],['incomplete','待核实'],['missing','待核实']]){
 const row=tableRows.find(r=>r.includes(name+'-drama'));
 const cells=row.match(/<td(?:\s[^>]*)?>[\s\S]*?<\/td>/g);
 assert.match(cells[6],new RegExp('>'+expected+'<'),name);
 assert.match(cells[7],name==='public'?/>已生成</:/>未生成</,'task generation is distinct from completion');
 if(name==='scheduled')assert.match(cells[5],/>已上传</,'scheduled upload stays uploaded');
}
""")


def test_sync_warning_colors_follow_latest_results_and_clear():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
let warnings=[{code:'multiple_candidates',message:'存在多个未公开视频',severity:'warning'}];
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"频道"}]');
 if(path.endsWith('/youtube-videos/sync'))return new Response('{"fetched":1}');
 const review={sync_complete:true,warnings,videos:[],channel_language:'en',channel_timezone:'UTC'};
 if(path.startsWith('/api/v3/schedules/overview'))return new Response(JSON.stringify([{schedule_id:'s1',chinese_title:'剧',video_sync:review}]));
 if(path.includes('/youtube-review'))return new Response(JSON.stringify(review));
 return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(action){
 const button={dataset:{action,id:'s1'},closest:()=>null};
 await page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
}
await click('go-schedules');
assert.match(page.nodes.get('viewRoot').innerHTML,/video-warning is-amber/);
await click('schedule-video-review');
assert.match(page.nodes.get('modalBody').innerHTML,/video-review-issues is-amber/);
warnings.push({code:'youtube_blocked',message:'YouTube 已屏蔽',severity:'error'});
await click('sync-schedule-channel');
assert.match(page.nodes.get('viewRoot').innerHTML,/video-warning is-red/);
await click('schedule-video-review');
assert.match(page.nodes.get('modalBody').innerHTML,/video-review-issues is-red/);
warnings=[];
await click('sync-schedule-channel');
assert.doesNotMatch(page.nodes.get('viewRoot').innerHTML,/video-warning/);
await click('schedule-video-review');
assert.doesNotMatch(page.nodes.get('modalBody').innerHTML,/video-review-issues/);
const css=require('fs').readFileSync(process.argv[1]+'/assets/styles.css','utf8');
assert.match(css,/\.video-warning\.is-amber\s*\{[^}]*color:\s*var\(--amber\)/);
""")


def test_normal_video_cell_is_compact_and_does_not_duplicate_empty_state():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const selected={video_id:'3892TkDbQzc',state:'private',warnings:[]};
const rows=[
 {schedule_id:'s1',chinese_title:'已上传的剧',source_video_id:selected.video_id,source_video_url:'https://youtu.be/'+selected.video_id,
  video_sync:{sync_complete:true,selected,warnings:[],videos:[selected]}},
 {schedule_id:'s2',chinese_title:'未上传的剧',video_sync:{sync_complete:true,selected:null,warnings:[],videos:[],empty_label:'本次未上传'}},
 {schedule_id:'s3',chinese_title:'只有视频ID的剧',source_video_id:'idOnly12345'}
];
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"频道"}]');
 if(path.startsWith('/api/v3/schedules/overview'))return new Response(JSON.stringify(rows));
 return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
const button={dataset:{action:'go-schedules'},closest:()=>null};
await page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
const html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/schedule-video-main/);
assert.match(html,/私享 · 未定时/);
assert.doesNotMatch(html,/video-warning/);
assert.doesNotMatch(html,/查看／选择视频/);
assert.doesNotMatch(html,/待补充/);
assert.equal((html.match(/本次未上传/g)||[]).length,1);
assert.match(html,/aria-label="编辑视频信息"/);
assert.match(html,/查看视频/);
assert.match(html,/<span class="schedule-video-id mono">idOnly12345<\/span>/);
""")


def test_schedule_warning_opens_candidates_without_saving_and_explicit_choice_saves():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const requests=[];
const review={sync_complete:true,channel_language:'ar',channel_timezone:'Asia/Riyadh',planned_at:'2026-10-26T12:00:00Z',
 warnings:[{code:'language_error',message:'语言错误：英语 → 阿拉伯语频道'}],
 videos:[{video_id:'wrong-lang1',title:'测试剧_英语',language_check:'mismatch',state:'private',selectable:false,warnings:[]},
 {video_id:'arabic-new1',title:'测试剧_阿拉伯语',language_check:'match',state:'scheduled',selectable:true,scheduled_at:'2026-10-26T12:00:00Z',warnings:[]}]
};
const item={schedule_id:'s1',chinese_title:'测试剧',drama_code:'DRM-1',video_sync:review};
const page=start(process.argv[1],auth,async(path,opts)=>{
 requests.push([path,opts]);
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"阿拉伯频道"}]');
 if(path.startsWith('/api/v3/schedules/overview'))return new Response(JSON.stringify([item]));
 if(path.includes('/youtube-review')||path.includes('/youtube-selection'))return new Response(JSON.stringify(review));
 return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(action,id,extra={}){
 const button={dataset:{action,id,...extra},closest:()=>null};
 await page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
}
await click('go-schedules');
assert.match(page.nodes.get('viewRoot').innerHTML,/sync-schedule-channel/);
assert.match(page.nodes.get('viewRoot').innerHTML,/video-warning/);
await click('schedule-video-review','s1');
assert.match(page.nodes.get('modalBody').innerHTML,/语言错误/);
assert.match(page.nodes.get('modalBody').innerHTML,/已定时/);
assert.doesNotMatch(page.nodes.get('modalBody').innerHTML,/data-video-id="wrong-lang1"/);
assert.equal(requests.filter(([p])=>p.includes('/youtube-selection')).length,0);
await click('select-schedule-youtube','s1',{videoId:'arabic-new1'});
assert.equal(requests.filter(([p])=>p.includes('/youtube-selection')).length,1);
""")


def test_unbound_uploaded_videos_show_ids_and_upload_status_including_processing_and_blocked():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const rows=['private','processing','error'].map((state,i)=>({schedule_id:'s'+i,chinese_title:'uploaded-'+state,
 is_uploaded:false,is_published:false,video_sync:{sync_complete:true,selected:null,warnings:[],
 videos:[{video_id:'existing-id-'+i,state,selectable:state==='private'}]}}));
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
 if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
 if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"c1","display_name":"频道"}]');
 if(path.startsWith('/api/v3/schedules/channel-view'))return new Response(JSON.stringify({page:1,page_size:50,total:rows.length,items:rows}));
 return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
async function click(action,extra={}){
 const button={dataset:{action,...extra},closest:()=>null};
 await page.document.emit('click',{target:{closest:s=>s==='[data-action]'?button:null}});
}
await click('go-schedules');await click('schedule-view-mode',{mode:'full'});
const html=page.nodes.get('viewRoot').innerHTML;
for(let i=0;i<rows.length;i++){
 const row=html.match(/<tr>[\s\S]*?<\/tr>/g).find(r=>r.includes(rows[i].chinese_title));
 assert.match(row,new RegExp('https://www.youtube.com/watch\\?v=existing-id-'+i));
 assert.match(row,/未绑定本次排期/);
 const cells=row.match(/<td(?:\s[^>]*)?>[\s\S]*?<\/td>/g);
 assert.match(cells[5],/>已上传</);
 assert.doesNotMatch(row,/本次未上传/);
}
assert.match(html,/视频处理中/);assert.match(html,/视频处理异常/);
""")
