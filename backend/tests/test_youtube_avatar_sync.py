from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from test_v14_api import PRINCIPAL, client
from test_v14_runs import store
from zhiju import auth_context
from zhiju.database import TenantSession
from zhiju.models import AccountChannelAuthorization, Channel, OAuthGrant
from zhiju.services import youtube_channel_sync
from zhiju.services.youtube_oauth import YouTubeAuthorizationRequired

ROUTE = '/api/v3/channels/youtube-avatars/sync'


def test_avatar_sync_refreshes_company_channel_list_and_preserves_missing(client, store, monkeypatch):
    principal = replace(PRINCIPAL, permissions=frozenset({'channel.manage'}))
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as session:
        session.get(Channel, 'channel-a').youtube_avatar_url = 'https://example.com/old.png'
        for key in ('unlisted', 'same'):
            session.add(Channel(id=key, original_name=key, youtube_channel_id=f'UC-{key}',
                youtube_avatar_url='https://example.com/keep.png', status='active'))
        session.add(Channel(id='deleted', original_name='deleted', youtube_channel_id='UC-deleted',
            status='deleted', deleted_at=datetime.now(timezone.utc)))
        for key in ('stale', 'working'):
            session.add(OAuthGrant(id=key, account_id=f'account-{key}', provider_subject=key,
                credential_ref='test', status='active'))
            session.add(AccountChannelAuthorization(id=key, account_id=f'account-{key}',
                channel_id='channel-a', oauth_grant_id=key, status='active',
                verified_youtube_channel_id='UC-a', verified_at=datetime(2026, 11, 9 if key == 'stale' else 8)))
        session.commit()

    def token(_session, _store, grant):
        if grant.id == 'stale':
            raise YouTubeAuthorizationRequired('expired')
        return 'test-token'

    calls = []
    def request(url, access_token):
        calls.append(access_token)
        query = parse_qs(urlsplit(url).query)
        assert urlsplit(url).path == '/youtube/v3/channels'
        assert set(query['id'][0].split(',')) == {'UC-a', 'UC-same', 'UC-unlisted'}
        assert query['part'] == ['snippet']
        return {'items': [
            {'id': 'UC-a', 'snippet': {'title': 'Do not change local title', 'thumbnails': {
                'default': {'url': 'https://example.com/small.png'}, 'high': {'url': 'https://example.com/new.png'}}}},
            {'id': 'UC-same', 'snippet': {'thumbnails': {'default': {'url': 'https://example.com/keep.png'}}}},
            {'id': 'UC-b', 'snippet': {'thumbnails': {'high': {'url': 'https://example.com/foreign.png'}}}},
        ]}

    monkeypatch.setattr(youtube_channel_sync, 'ensure_grant_access_token', token)
    monkeypatch.setattr(youtube_channel_sync, '_youtube_request_json', request)
    from zhiju.api import youtube_oauth
    monkeypatch.setattr(youtube_oauth, 'get_settings', lambda: SimpleNamespace(deployment='local', device_role='builder'))
    assert client.post(ROUTE).status_code == 403
    client.app.dependency_overrides[auth_context.get_current_principal] = lambda: principal
    response = client.post(ROUTE)
    assert response.status_code == 200, response.text
    assert response.json() == {'updated': 1, 'unchanged': 1, 'missing': ['unlisted']}
    assert calls == ['test-token']
    rows = {row['channel_id']: row for row in client.get('/api/v3/channels/overview').json()}
    assert rows['channel-a']['youtube_avatar_url'] == 'https://example.com/new.png'
    assert rows['channel-a']['original_name'] == '频道'
    assert rows['unlisted']['youtube_avatar_url'] == 'https://example.com/keep.png'
    assert client.post(ROUTE).json() == {'updated': 0, 'unchanged': 2, 'missing': ['unlisted']}
    def expired(*args):
        raise YouTubeAuthorizationRequired('expired')

    monkeypatch.setattr(youtube_channel_sync, 'ensure_grant_access_token', expired)
    unavailable = client.post(ROUTE)
    assert unavailable.status_code == 409
    assert '请先授权一个频道' in unavailable.json()['detail']
    with TenantSession(store, info={'tenant_id': 'tenant-a'}) as session:
        assert session.get(Channel, 'channel-a').youtube_avatar_url == 'https://example.com/new.png'
    with TenantSession(store, info={'tenant_id': 'tenant-b'}) as session:
        assert session.get(Channel, 'channel-b').youtube_avatar_url is None
