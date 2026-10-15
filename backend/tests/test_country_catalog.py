import pytest

from zhiju.services.country_catalog import get_country_option, list_country_options


def test_country_catalog_returns_exact_code_and_recommendations() -> None:
    country = get_country_option("us")

    assert country.code == "US"
    assert country.name_zh == "美国"
    assert country.recommended_language == "en"
    assert "America/New_York" in country.timezones
    assert country.recommended_timezone in country.timezones


def test_country_catalog_contains_current_operating_markets() -> None:
    codes = {country.code for country in list_country_options()}

    assert {"US", "ID", "PH", "BR", "ES", "TR", "BD", "SA"} <= codes


def test_country_catalog_rejects_unknown_code() -> None:
    with pytest.raises(ValueError, match="国家或地区代码无效"):
        get_country_option("XX")


def test_france_is_available_for_import_with_french_and_paris_timezone() -> None:
    country = get_country_option("FR")
    assert country in list_country_options()
    assert country.name_zh == "法国"
    assert country.recommended_language == "fr"
    assert country.recommended_timezone == "Europe/Paris"
    assert country.recommended_timezone in country.timezones
