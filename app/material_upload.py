"""Validate locally stored downloads without executing or extracting uploaded content."""
import base64
import binascii
import hashlib
import io
from pathlib import PurePath
from unicodedata import category
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

MAX_MATERIAL_BYTES = 5 * 1024 * 1024
MATERIAL_REQUEST_BYTES = 7 * 1024 * 1024
MAX_ASSIGNMENT_FILE_BYTES = 128 * 1024 * 1024
OFFICE_FILES = {'docx': 'word/document.xml', 'pptx': 'ppt/presentation.xml', 'xlsx': 'xl/workbook.xml'}
FILE_SIGNATURES = {'pdf': b'%PDF-', 'png': b'\x89PNG\r\n\x1a\n', 'jpg': b'\xff\xd8\xff', 'jpeg': b'\xff\xd8\xff'}
FILE_FORMATS = (*FILE_SIGNATURES, *OFFICE_FILES, 'txt', 'md')
FILE_POLICY = "sandbox; default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"


class MaterialUpload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=4 * ((MAX_MATERIAL_BYTES + 2) // 3))


def matches_format(content, extension):
    if extension in FILE_SIGNATURES:
        return content.startswith(FILE_SIGNATURES[extension])
    if extension in OFFICE_FILES:
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                return {'[Content_Types].xml', OFFICE_FILES[extension]} <= names and not any(
                    name.casefold().endswith('vbaproject.bin') for name in names)
        except (BadZipFile, ValueError):
            return False
    try:
        return all(char in '\n\r\t' or category(char) != 'Cc' for char in content.decode('utf-8'))
    except UnicodeDecodeError:
        return False


def decode_upload(upload):
    name = upload.name.strip()
    extension = PurePath(name).suffix.lower().removeprefix('.')
    if extension not in FILE_FORMATS or any(char in '/\\:' or category(char).startswith('C') for char in name):
        raise HTTPException(422, 'Выберите файл разрешённого формата с обычным именем')
    try:
        content = base64.b64decode(upload.content, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'Не удалось прочитать приложенный файл') from None
    if not 0 < len(content) <= MAX_MATERIAL_BYTES:
        raise HTTPException(422, 'Размер файла должен быть от 1 байта до 5 МиБ')
    if not matches_format(content, extension):
        raise HTTPException(422, 'Содержимое файла не соответствует формату')
    return dict(file_name=name, file_size=len(content), file_digest=hashlib.sha256(content).hexdigest(), file_content=content)


def download_upload(name, content):
    return Response(content, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name, safe=''),
        'Content-Security-Policy': FILE_POLICY,
    })
