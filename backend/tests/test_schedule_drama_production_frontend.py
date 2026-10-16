from test_auth_frontend_contract import run_node


def test_all_schedule_modes_show_production_badge_after_drama_code():
    run_node(r"""
const {start}=require(process.argv[1]+'/backend/tests/frontend_dom_harness.js');
const items=['completed','in_progress','not_started'].map((status,i)=>({
  schedule_id:'s'+i,drama_code:'DRM-'+i,chinese_title:'剧目'+i,
  drama_production_status:status,channel_id:'channel-a',slot_type:'main',
  slot_number:1,slot_local_time:'18:00',schedule_status:'planned'
}));
const page=start(process.argv[1],auth,async(path)=>{
  if(path==='/api/v3/auth/me')return new Response(JSON.stringify(principal));
  if(path==='/api/health')return new Response('{"ok":true,"database":{"ok":true}}');
  if(path==='/api/v3/realtime/config')return new Response('{"enabled":false,"device_role":"worker"}');
  if(path==='/api/v3/demo-data/feishu-first20')return new Response('{"active":false}');
  if(path==='/api/v3/channels/overview')return new Response('[{"channel_id":"channel-a","display_name":"测试频道"}]');
  if(path.startsWith('/api/v3/schedules/overview'))return new Response(JSON.stringify(items));
  if(path.startsWith('/api/v3/schedules/channel-view'))return new Response(JSON.stringify({items,total:3,page:1,page_size:50}));
  return new Response('[]');
});
for(let i=0;i<4;i++)await page.tick();
for(const mode of ['day','full','all-day']){
  const button={dataset:{action:'schedule-view-mode',mode},closest:()=>null};
  await page.document.emit('click',{target:{closest:selector=>selector==='[data-action]'?button:null}});
  const html=page.nodes.get('viewRoot').innerHTML;
  assert.match(html,/DRM-0<\/span>\s*<span class="tag is-green"[^>]*>完成<\/span>/);
  assert.match(html,/DRM-1<\/span>\s*<span class="tag is-blue"[^>]*>未完成<\/span>/);
  assert.match(html,/DRM-2<\/span>\s*<span class="tag "[^>]*>未开始<\/span>/);
  assert.match(html,/planned/);
}
""")
