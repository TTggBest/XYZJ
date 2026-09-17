from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountryOption:
    code: str
    name_zh: str
    recommended_language: str
    recommended_timezone: str
    timezones: tuple[str, ...]


_COUNTRIES = (
    CountryOption("AE", "阿联酋", "ar", "Asia/Dubai", ("Asia/Dubai",)),
    CountryOption("BD", "孟加拉国", "bn", "Asia/Dhaka", ("Asia/Dhaka",)),
    CountryOption(
        "BR",
        "巴西",
        "pt-BR",
        "America/Sao_Paulo",
        ("America/Sao_Paulo", "America/Manaus"),
    ),
    CountryOption("ES", "西班牙", "es", "Europe/Madrid", ("Europe/Madrid",)),
    CountryOption("ID", "印度尼西亚", "id", "Asia/Jakarta", ("Asia/Jakarta", "Asia/Makassar")),
    CountryOption("IN", "印度", "hi", "Asia/Kolkata", ("Asia/Kolkata",)),
    CountryOption("MX", "墨西哥", "es", "America/Mexico_City", ("America/Mexico_City",)),
    CountryOption("PH", "菲律宾", "fil", "Asia/Manila", ("Asia/Manila",)),
    CountryOption("SA", "沙特阿拉伯", "ar", "Asia/Riyadh", ("Asia/Riyadh",)),
    CountryOption("TR", "土耳其", "tr", "Europe/Istanbul", ("Europe/Istanbul",)),
    CountryOption(
        "US",
        "美国",
        "en",
        "America/New_York",
        ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"),
    ),
)
_BY_CODE = {country.code: country for country in _COUNTRIES}


def list_country_options() -> list[CountryOption]:
    return sorted(_COUNTRIES, key=lambda country: country.name_zh)


def get_country_option(code: str) -> CountryOption:
    country = _BY_CODE.get(code.strip().upper())
    if country is None:
        raise ValueError("国家或地区代码无效")
    return country
