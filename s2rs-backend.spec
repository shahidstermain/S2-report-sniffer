# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


_SPEC_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SPEC_DIR / 'backend'


def _collect_backend_datas():
    datas = []
    for path in sorted(_BACKEND_DIR.glob('*.py')):
        if path.name == 'conftest.py' or path.name.startswith('test_'):
            continue
        datas.append((str(path), 'backend'))

    migrations_dir = _BACKEND_DIR / 'migrations'
    if migrations_dir.is_dir():
        for path in sorted(migrations_dir.glob('*.py')):
            datas.append((str(path), 'backend/migrations'))

    return datas


a = Analysis(
    ['backend/desktop_entry.py'],
    pathex=['backend'],
    binaries=[],
    datas=_collect_backend_datas(),
    hiddenimports=[
        'fastapi',
        'starlette',
        'starlette.middleware.cors',
        'starlette.middleware.base',
        'starlette.staticfiles',
        'pydantic',
        'pydantic_core',
        'pydantic_settings',
        'aiofiles',
        'uvicorn',
        'uvicorn.importer',
        'uvicorn.config',
        'python_dotenv',
        'pythonjsonlogger.jsonlogger',
        'httpx',
        'slowapi',
        'slowapi.middleware',
        'python_multipart',
        'tenacity',
        'requests',
        'rich',
        'rich.console',
        'rich.table',
        'rich.progress',
        'rich.logging',
        'importlib_metadata',
        'multidict',
        'anyio',
        'h11',
        'click',
        'jsonschema',
        'email_validator',
        'annotated_doc',
        'annotated_types',
        'aiohappyeyeballs',
        'aiosignal',
        'attrs',
        'fsspec',
        'packaging',
        'rpds',
        'propcache',
        'yarl',
        'typing_extensions',
        'tzdata',
        'zipp',
        'referencing',
        'jsonschema_specifications',
        'uritemplate',
        'markdown_it_py',
        'mdurl',
        'pygments',
        'jinja2',
        'markupsafe',
        'distro',
        'certifi',
        'idna',
        'charset_normalizer',
        'urllib3',
        'frozenlist',
        'pathlib',
        'contextvars',
        'dataclasses',
        'pydantic.fields',
        'pydantic.models',
        'pydantic.main',
        'pydantic.config',
        'pydantic.datetime_parse',
        'pydantic.env_utils',
        'starlette.routing',
        'starlette.responses',
        'starlette.requests',
        'starlette.middleware',
        'starlette.applications',
        'starlette.convertors',
        'fastapi.applications',
        'fastapi.routing',
        'fastapi.responses',
        'fastapi.encoders',
        'fastapi.utils',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.parsers',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.protocol',
        'fastapi.openapi',
        'fastapi.openapi.utils',
        'fastapi.openapi.docs',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='s2rs-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
