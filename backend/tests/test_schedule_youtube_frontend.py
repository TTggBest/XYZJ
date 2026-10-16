from test_auth_frontend_contract import run_node


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
