"""Environment configuration. No service credentials are shipped in source."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, unquote

APP_ENVIRONMENTS = {'development', 'test', 'production'}
DEMO_LOGINS = frozenset({'alina.demo', 'mark.demo', 'dean.demo', 'orlov.demo',
                         'ryabinina.demo', 'lastochkina.demo', 'zorin.demo',
                         'schedule.demo', 'registry.demo', 'union.demo', 'vuc.demo'})


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, str(default)).lower().strip()
    if value not in {'true', 'false', '1', '0'}:
        raise RuntimeError(f'{name} must be true or false')
    return value in {'true', '1'}


@dataclass(frozen=True)
class Settings:
    app_env: str
    demo_mode: bool
    cookie_secure: bool
    public_origin: str
    allowed_hosts: tuple[str, ...]

    def validate(self, database_url: str) -> None:
        if self.app_env not in APP_ENVIRONMENTS:
            raise RuntimeError('APP_ENV must be development, test or production')
        if self.public_origin:
            origin = urlsplit(self.public_origin)
            if origin.scheme not in {'http', 'https'} or not origin.netloc or origin.path not in {'', '/'} or origin.query or origin.fragment or origin.username:
                raise RuntimeError('PUBLIC_ORIGIN must be an HTTP(S) origin without a path or credentials')
        if self.app_env == 'production':
            if not self.public_origin.startswith('https://') or not self.cookie_secure:
                raise RuntimeError('Production requires HTTPS PUBLIC_ORIGIN and COOKIE_SECURE=true')
            if not self.allowed_hosts or any('*' in host for host in self.allowed_hosts):
                raise RuntimeError('Production requires explicit ALLOWED_HOSTS')
            if not database_url.startswith('postgresql'):
                raise RuntimeError('Production requires PostgreSQL DATABASE_URL')
            database = urlsplit(database_url)
            try:
                password = unquote(database.password or '', errors='strict')
            except UnicodeDecodeError:
                raise RuntimeError('Production database password has invalid URL encoding') from None
            if not database.username or len(password) < 32 or any(marker in password.lower() for marker in ('replace_with', 'change_me', 'changeme')):
                raise RuntimeError('Production database requires a dedicated username and a random password of at least 32 characters')
            if urlsplit(self.public_origin).hostname not in self.allowed_hosts:
                raise RuntimeError('PUBLIC_ORIGIN host must be included in ALLOWED_HOSTS')


def load_settings() -> Settings:
    app_env = os.environ.get('APP_ENV', 'development').strip().lower()
    if app_env not in APP_ENVIRONMENTS:
        raise RuntimeError('APP_ENV must be development, test or production')
    return Settings(
        app_env=app_env,
        demo_mode=env_bool('DEMO_MODE', app_env != 'production'),
        cookie_secure=env_bool('COOKIE_SECURE', False),
        public_origin=os.environ.get('PUBLIC_ORIGIN', '').rstrip('/'),
        allowed_hosts=tuple(x.strip() for x in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',') if x.strip()),
    )


settings = load_settings()
