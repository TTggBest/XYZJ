from cryptography.fernet import Fernet

from zhiju.config import Settings


def test_cloud_youtube_oauth_settings_use_fixed_https_callback() -> None:
    settings = Settings(
        _env_file=None,
        env="production",
        deployment="cloud",
        database_url="mysql+pymysql://app:secret@127.0.0.1/zhiju_cloud",
        migration_database_url="mysql+pymysql://migrator:secret@127.0.0.1/zhiju_cloud",
        host="127.0.0.1",
        youtube_oauth_client_id="client-id.apps.googleusercontent.com",
        youtube_oauth_client_secret="client-secret",
        oauth_encryption_key=Fernet.generate_key().decode(),
    )

    assert settings.youtube_oauth_redirect_uri == (
        "https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback"
    )
    assert settings.youtube_oauth_configured is True


def test_cloud_youtube_oauth_is_unconfigured_when_any_secret_is_missing() -> None:
    settings = Settings(
        _env_file=None,
        env="production",
        deployment="cloud",
        database_url="mysql+pymysql://app:secret@127.0.0.1/zhiju_cloud",
        migration_database_url="mysql+pymysql://migrator:secret@127.0.0.1/zhiju_cloud",
        host="127.0.0.1",
        youtube_oauth_client_id="client-id.apps.googleusercontent.com",
        youtube_oauth_client_secret="",
        oauth_encryption_key="",
    )

    assert settings.youtube_oauth_configured is False


def test_google_proxy_is_optional_and_defaults_to_direct_connection() -> None:
    settings = Settings(
        _env_file=None,
        env="production",
        deployment="cloud",
        database_url="mysql+pymysql://app:secret@127.0.0.1/zhiju_cloud",
        host="127.0.0.1",
    )

    assert settings.google_proxy_url == ""
