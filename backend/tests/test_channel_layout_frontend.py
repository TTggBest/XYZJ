from test_auth_frontend_contract import run_node
from test_channel_ledger_frontend import BOOT


BOOT_ORDER = BOOT.replace("'youtube.manage'", "'youtube.manage','channel.manage'").replace(
    "const ledger=", "channels[0].production_material_issues=['频道基础资料','标题模板']; channels[1].production_material_issues=[];\nconst ledger="
).replace(
    "if(path==='/api/v3/channels/overview')", "if(path==='/api/v3/channels/order'){const ids=JSON.parse(options.body).channel_ids;ids.forEach((id,index)=>channels.find(c=>c.channel_id===id).sort_order=index+1);return new Response(JSON.stringify(channels));}\n if(path==='/api/v3/channels/overview')"
).replace(
    "});\npage.document.querySelector", "}, {FormData: class {constructor(form){this.form=form;} entries(){return Object.entries(this.form.values);}}});\npage.document.querySelector"
)


def test_channel_layout_gives_ledger_its_own_column_and_opens_issue_details():
    run_node(BOOT_ORDER + r'''
let html=page.nodes.get('viewRoot').innerHTML;
assert.ok(!html.includes('channelSortOrder'),'there is one authoritative saved channel order');
assert.match(html,/channel-ledger-cell[\s\S]*data-action="channel-ledger"/);
const actionCells=[...html.matchAll(/<td class="channel-action-cell">([\s\S]*?)<\/td>/g)].map(m=>m[1]);
assert.equal(actionCells.length,2);
assert.ok(actionCells.every(cell=>!cell.includes('channel-ledger') && !cell.includes('move-channel') && !cell.includes('delete-channel')));
assert.match(html,/channel-position-cell[\s\S]*data-action="move-channel"/);
assert.doesNotMatch(html,/identity-cell[\s\S]*channel-ledger-entry/);
assert.match(html,/data-action="channel-material-issues"/);
assert.ok(!html.includes('标题模板'),'missing material details must not stretch the row');
await click('channel-material-issues',{id:'c1'});
assert.match(page.nodes.get('modalBody').innerHTML,/标题模板/);
assert.match(page.nodes.get('modalBody').innerHTML,/频道基础资料/);
''')


def test_channel_move_saves_full_order_including_filtered_out_channels():
    run_node(BOOT_ORDER + r'''
page.nodes.set('channelLanguageFilter',{value:'en'});
await click('apply-channel-list-filters');
assert.ok(!page.nodes.get('viewRoot').innerHTML.includes('data-value="法语频道"'));
await click('move-channel',{id:'c2'});
assert.match(page.nodes.get('modalBody').innerHTML,/保存顺序/);
const form={id:'channelOrderForm',dataset:{},values:{channel_id:'c2',position:'0'}};
await page.document.emit('submit',{target:form}); await settle();
assert.ok(calls.some(([p,m])=>p==='/api/v3/channels/order' && m==='PUT'));
await click('reset-channel-list-filters');
let html=page.nodes.get('viewRoot').innerHTML;
assert.ok(html.indexOf('data-value="英语频道"')<html.indexOf('data-value="法语频道"'));
await click('back-ledger-channels');
html=page.nodes.get('viewRoot').innerHTML;
assert.ok(html.indexOf('data-value="英语频道"')<html.indexOf('data-value="法语频道"'),'saved order survives reloading the channel page');
assert.equal(form.dataset.busy,'false');
''')


def test_channel_maintenance_actions_open_from_more_instead_of_expanding_the_row():
    run_node(BOOT_ORDER + r'''
let html=page.nodes.get('viewRoot').innerHTML;
assert.match(html,/data-action="channel-more"/);
assert.ok(!html.includes('data-action="delete-channel"'));
await click('channel-more',{id:'c1'});
const menu=page.nodes.get('modalBody').innerHTML;
assert.match(menu,/channel-management-menu/);
assert.match(menu,/data-action="configure-channel-logo"/);
await click('configure-channel-logo',{id:'c1'});
assert.match(page.nodes.get('modalTitle').textContent,/频道 Logo 配置/);
''')
