from copy import deepcopy

import pytest
from test_v14_runs import store, configure
from zhiju.database import TenantSession
from zhiju.models import Channel
from zhiju.services.v14_runs import create_run, save_settings
from zhiju.services.identity import ConflictError


@pytest.mark.parametrize('language',['印地','印地语','Hindi',' hi '])
def test_hindi_material_names_match_hi_without_changing_original_material(store,language):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        config=deepcopy(configure(s).payload)
        s.get(Channel,'channel-a').default_language='hi'
        config['channel_inputs']['channel-a']['language']=language
        save_settings(s,config)
        run=create_run(s,'work-a')
        assert run.status=='queued'
        assert run.input_snapshot['channel']['language']==language


def test_indonesian_material_does_not_match_hindi_channel(store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        config=deepcopy(configure(s).payload)
        s.get(Channel,'channel-a').default_language='hi'
        config['channel_inputs']['channel-a']['language']='印尼'
        save_settings(s,config)
        with pytest.raises(ConflictError,match='语言'):
            create_run(s,'work-a')
