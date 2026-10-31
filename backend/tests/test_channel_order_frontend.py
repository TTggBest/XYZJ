from test_auth_frontend_contract import run_node


def test_channels_and_records_keep_one_order_across_refreshes():
    run_node(r"""
const order=require(process.argv[1]+'/assets/operations-page-data.js');
const channels=[
 {channel_id:'new',original_name:'Alpha',created_at:'2026-10-29T00:00:00Z'},
 {channel_id:'old',original_name:'Zulu',created_at:'2026-10-16T00:00:00Z'},
];
assert.deepEqual(order.sortChannels(channels).map(c=>c.channel_id),['old','new']);
assert.equal(channels[0].channel_id,'new','sorting must not mutate incoming data');
const rows=[
 {channel_id:'new',task_id:'n2',planned_beijing_time:'2026-11-03T20:00:00'},
 {channel_id:'old',task_id:'o2',planned_beijing_time:'2026-11-03T23:00:00'},
 {channel_id:'new',task_id:'n1',planned_beijing_time:'2026-11-03T12:00:00'},
 {channel_id:'old',task_id:'o1',planned_beijing_time:'2026-11-03T07:00:00'},
];
const ids=items=>items.map(r=>r.task_id);
assert.deepEqual(ids(order.sortChannelRecords(rows,channels)),['o1','o2','n1','n2']);
assert.deepEqual(ids(order.sortChannelRecords([...rows].reverse(),[...channels].reverse())),['o1','o2','n1','n2']);
const tied=rows.map(r=>({...r,planned_beijing_time:'2026-11-03T12:00:00'}));
assert.deepEqual(ids(order.sortChannelRecords(tied,channels)),ids(order.sortChannelRecords([...tied].reverse(),channels)));
assert.deepEqual(ids(order.sortChannelRecords(rows.map(r=>({...r,updated_at:'2026-12-01',execution_status:'completed'})),channels)),['o1','o2','n1','n2']);
""")


def test_workorders_and_packages_group_channels_on_every_navigation():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const channels=[
 {channel_id:'new',display_name:'New channel',created_at:'2026-10-29T00:00:00Z'},
 {channel_id:'old',display_name:'Old channel',created_at:'2026-10-16T00:00:00Z'},
];
const rows=[['new','20','new-late'],['old','23','old-late'],['new','12','new-early'],['old','07','old-early']].map(([channel,hour,id])=>({
 channel_id:channel,channel_name:channel==='old'?'Old channel':'New channel',task_id:id,work_order_id:id,
 package_id:id,chinese_title:id,task_status:'pending_dispatch',nodes:{},
 planned_beijing_time:`2026-11-03T${hour}:00:00`,planned_utc_time:`2026-11-03T${hour}:00:00Z`,
 titles:[],covers:[],community_posts:[],playlists:[],media_assets:[],
}));
let reverse=false;
const page=start(process.argv[1],auth,async(path)=>{
 if(path==='/api/v3/workflow-versions')return new Response('{"versions":[],"default_id":null}');
 if(path==='/api/v3/auth/me')return new Response(JSON.stringify(superUser));
 if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
 if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"builder"}');
 if(path==='/api/v3/channels/overview')return new Response(JSON.stringify(reverse?[...channels].reverse():channels));
 if(path.startsWith('/api/v3/tasks/overview')||path.startsWith('/api/v3/packages/operations-overview'))
  return new Response(JSON.stringify(reverse?[...rows].reverse():rows));
 return new Response('[]');
});
for(let i=0;i<8;i++)await page.tick();
for(const view of ['workorders','packages','workorders','packages']){
 reverse=!reverse;
 await page.document.emit('click',{target:{closest:s=>s==='[data-view]'?{dataset:{view}}:null}});
 for(let i=0;i<8;i++)await page.tick();
 const html=page.nodes.get('viewRoot').innerHTML;
 const markers=view==='packages'
  ? [...html.matchAll(/data-package-id="([^"]+)"/g)].map(m=>m[1])
  : [...html.matchAll(/<span class="cell-main">(old-early|old-late|new-early|new-late)<\/span>/g)].map(m=>m[1]);
 const unique=[...new Set(markers)].filter(x=>rows.some(r=>r.task_id===x));
 assert.deepEqual(unique,['old-early','old-late','new-early','new-late'],view+' changed order after navigation');
 assert.ok(html.includes('排序：频道录入先后 → 计划发布时间'));
 if(view==='packages')assert.ok(html.indexOf('value="old"')<html.indexOf('value="new"'),'channel dropdown differs from rows');
}
""")
