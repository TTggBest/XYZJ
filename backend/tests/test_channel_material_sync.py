from sqlalchemy import select
from test_v14_runs import store
from zhiju.database import TenantSession
from zhiju.models import Channel,ChannelProfile,ChannelPinnedCommentTemplate,ChannelPlaylist
from zhiju.services.channel_material_sync import sync_material_rows,sync_channel_materials
from zhiju.services import channel_material_sync as module


def test_two_sheet_sync_refreshes_selected_channels_and_only_fills_old_blanks(store):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        old=Channel(original_name='old',youtube_channel_id='UC-old',default_language='id',timezone='Asia/Jakarta')
        new=Channel(original_name='new',youtube_channel_id='UC-new',default_language='en',timezone='America/New_York')
        s.add_all([old,new]);s.flush()
        s.add(ChannelProfile(channel_id=old.id,title_template='keep title',fixed_symbol='🔥',status='active'))
        s.commit()
        info=[{'频道名':'old','频道地址':'https://youtube.com/channel/UC-old','语言':'印尼语','标题模版':'overwrite forbidden','固定符号':'👑','置顶回复':'old source','播放列表1':'existing','播放列表说明1':'description'},
              {'频道名':'new','频道地址':'https://youtube.com/channel/UC-new','语言':'泰语','标题模版':'🔥 A B','固定符号':'🔥','本地昵称':'💎new','置顶回复':'thai','播放列表1':'thai playlist'}]
        brand=[{'频道名':'old','说明':'fill description','关键词':'one,two'},{'频道名':'new','说明':'thai description','关键词':'thai'}]
        result=sync_material_rows(s,info,brand,[new.id]);s.commit()
        profile=s.scalar(select(ChannelProfile).where(ChannelProfile.channel_id==old.id))
        assert profile.title_template=='keep title' and profile.fixed_symbol=='🔥'
        assert profile.description=='fill description'
        assert old.country_code=='ID' and old.country_name_zh=='印度尼西亚'
        assert new.default_language=='th' and new.country_code=='TH'
        assert new.operational_name=='💎new'
        assert s.scalar(select(ChannelProfile).where(ChannelProfile.channel_id==new.id)).fixed_symbol=='🔥'
        count=len(result['changes']);assert count>0
        result=sync_material_rows(s,info,brand,[new.id]);s.commit()
        assert result['changes']==[]
        assert len(list(s.scalars(select(ChannelPlaylist).where(ChannelPlaylist.channel_id==old.id))))==1


def test_explicit_workbook_preview_reads_only_information_and_branding_and_rolls_back(store,monkeypatch):
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        c=Channel(original_name='named',youtube_channel_id='UC-named',default_language='en',timezone='Asia/Bangkok');s.add(c);s.commit()
        calls=[]
        class Client:
            def sheet_id_by_title(self,wiki,title):calls.append(title);assert wiki=='chosen-source';return title
            def rows(self,wiki,sheet,column):
                return [{'频道名':'named','语言':'泰语'}] if sheet=='频道信息' else [{'频道名':'named','说明':'text'}]
        monkeypatch.setattr(module.source,'_client',Client)
        result=sync_channel_materials(s,'chosen-source',[c.id],preview=True)
        assert calls==['频道信息','频道装修'] and result['changes']
        s.refresh(c);assert c.default_language=='en'
        assert s.scalar(select(ChannelProfile).where(ChannelProfile.channel_id==c.id)) is None


def test_empty_source_terms_do_not_clear_existing_terms(store):
    from zhiju.models import ChannelKeyword
    with TenantSession(store,info={'tenant_id':'tenant-a'}) as s:
        c=Channel(original_name='terms',youtube_channel_id='UC-terms',default_language='th',timezone='Asia/Bangkok');s.add(c);s.flush()
        word=ChannelKeyword(channel_id=c.id,keyword='retained',keyword_type='keyword',language='th',source='feishu_channel_branding',status='active');s.add(word);s.commit()
        sync_material_rows(s,[{'频道名':'terms','语言':'泰语'}],[{'频道名':'terms','关键词':''}],[c.id]);s.commit()
        assert word.status=='active'
