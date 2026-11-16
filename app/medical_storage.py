"""Validate, rebuild and encrypt absence evidence before storing it."""
import base64
import binascii
import os
from pathlib import Path
import subprocess
import sys
from threading import BoundedSemaphore

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from .material_upload import FILE_SIGNATURES
from .medical_render import MAX_BYTES


MAX_ENCODED = 4 * ((MAX_BYTES + 2) // 3)
SUPPORTED = frozenset({'pdf', 'jpg', 'jpeg', 'png'})
_render_slot = BoundedSemaphore()


def certificate_key():
    value = os.environ.get('ATLAS_CERTIFICATE_KEY', '')
    try:
        key = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, binascii.Error):
        return None
    return key if len(key) == 32 else None


def encrypt(key, certificate_id, purpose, data):
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, f'atlas-absence:{certificate_id}:{purpose}'.encode())


def decrypt(key, certificate_id, purpose, ciphertext):
    try:
        return AESGCM(key).decrypt(ciphertext[:12], ciphertext[12:], f'atlas-absence:{certificate_id}:{purpose}'.encode())
    except (InvalidTag, ValueError):
        raise HTTPException(503, 'Содержимое справки временно недоступно') from None


def sanitized_upload(file):
    kind = file.name.strip().rpartition('.')[2].lower()
    if kind not in SUPPORTED:
        raise HTTPException(422, 'Поддерживаются PDF, JPG, JPEG и PNG')
    try:
        content = base64.b64decode(file.content, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'Не удалось прочитать файл') from None
    if not 0 < len(content) <= MAX_BYTES:
        raise HTTPException(422, 'Размер файла должен быть от 1 байта до 5 МиБ')
    if not content.startswith(FILE_SIGNATURES[kind]):
        raise HTTPException(422, 'Содержимое файла не соответствует формату')
    if not _render_slot.acquire(blocking=False):
        raise HTTPException(503, 'Обрабатывается другой документ. Повторите отправку через несколько секунд')
    try:
        env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR') if name in os.environ}
        result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).with_name('medical_render.py')), kind],
                                input=content, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, timeout=12)
    except subprocess.TimeoutExpired:
        raise HTTPException(422, 'Не удалось обработать файл. Попробуйте более простой PDF или фотографию') from None
    finally:
        _render_slot.release()
    if result.returncode or not result.stdout.startswith(b'%PDF-') or len(result.stdout) > MAX_BYTES:
        raise HTTPException(422, 'Не удалось обработать файл. Выберите читаемую фотографию или PDF до 8 страниц')
    return result.stdout
