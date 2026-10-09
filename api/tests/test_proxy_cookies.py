"""The browser must send refresh cookies to /api/auth through the proxy."""

from http.cookiejar import CookieJar

import httpx
from fastapi import Response

from app.config import Settings
from app.cookies import clear_session, set_session


def test_proxy_cookie_paths_refresh_and_clear():
    settings = Settings(_env_file=None, cookie_secure=True, cookie_path_prefix="/api")
    response = Response()
    set_session(response, settings=settings, access_token="access", refresh_token="refresh")
    jar = httpx.Cookies(CookieJar())
    request = httpx.Request("POST", "https://hirelens.example/api/auth/login")
    jar.extract_cookies(httpx.Response(200, headers=response.headers, request=request))
    refresh = httpx.Request("POST", "https://hirelens.example/api/auth/refresh")
    jar.set_cookie_header(refresh)
    assert "hirelens_refresh=refresh" in refresh.headers["cookie"]
    profile = httpx.Request("GET", "https://hirelens.example/api/auth/me")
    jar.set_cookie_header(profile)
    assert "hirelens_access=access" in profile.headers["cookie"]
    public = httpx.Request("GET", "https://hirelens.example/careers")
    jar.set_cookie_header(public)
    assert "cookie" not in public.headers
    cleared = Response()
    clear_session(cleared, settings=settings)
    jar.extract_cookies(httpx.Response(200, headers=cleared.headers, request=request))
    after = httpx.Request("POST", "https://hirelens.example/api/auth/refresh")
    jar.set_cookie_header(after)
    assert "cookie" not in after.headers
