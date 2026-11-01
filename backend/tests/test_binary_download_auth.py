from test_auth_frontend_contract import run_node


def test_binary_fetch_keeps_session_context_and_errors_use_existing_auth_handling():
    run_node(r'''
await auth.resolveBootstrap(async()=>principal);
const result=await auth.request(async(url,options)=>{
 assert.equal(url,'/api/v3/media-assets/id/content?download=true');
 assert.equal(options.credentials,'same-origin');assert.ok(!('responseType' in options));
 return new Response(new Uint8Array([1,2,3]),{headers:{'Content-Disposition':'attachment; filename="cover.png"'}});
},'/media-assets/id/content?download=true',{responseType:'blob'});
assert.equal(result.blob.size,3);assert.match(result.contentDisposition,/cover.png/);
await assert.rejects(auth.request(async()=>new Response('{"detail":"请登录"}',{status:401}),'/media-assets/id/content',{responseType:'blob'}),e=>e.status===401);
assert.equal(auth.current(),null);
''')


def test_binary_response_is_discarded_if_account_changes_while_reading_body():
    run_node(r'''
await auth.resolveBootstrap(async()=>principal);
let finish;
const pending=auth.request(async()=>({ok:true,headers:{get:()=>''},blob:()=>new Promise(resolve=>finish=resolve)}),'/media-assets/id/content',{responseType:'blob'});
await new Promise(resolve=>setImmediate(resolve));
auth.clear();finish(new Blob(['file']));
await assert.rejects(pending,e=>e.name==='AbortError');
''')
