# -*- mode: python ; coding: utf-8 -*-
import sys, os

block_cipher = None
_src = "/Users/shahidster/S2-report-sniffer/backend"
_bundle = os.path.join(getattr(sys, '_MEIPASS', _src), 'backend')

a = Analysis(
    ['desktop_entry.py'],
    pathex=[_src],
    binaries=[],
    datas=[
        (_src, 'backend'),
    ],
    hiddenimports=[
        'fastapi','starlette','starlette.middleware.base','starlette.middleware.errors',
        'starlette.middleware.cors','starlette.middleware.gzip','starlette.middleware.trusted_host',
        'starlette.responses','starlette.routing','starlette.staticfiles','starlette.status',
        'pydantic','pydantic.generated','pydantic.functional_validators','pydantic.functional_serializers',
        'pydantic.type_adapter_utils','pydantic.validators','pydantic.dataclasses',
        'pydantic_core','pydantic_core.builders','pydantic_core.infer_protected_function',
        'pydantic_core.init_subclass','pydantic_core.main','pydantic_core.schema_metadata',
        'pydantic_core.schema_type','pydantic_core.type_adapter_info','pydantic_core.typing_utils',
        'pydantic_core.validators','aiofiles','aiofiles.base','aiofiles.threadpoolutils',
        'uvicorn','uvicorn.loops','uvicorn.loops.asyncio','uvicorn.loops.auto',
        'uvicorn.config','uvicorn.logging','uvicorn.structured','uvicorn.middleware',
        'uvicorn.error','uvicorn.importer','uvicorn.protocols','uvicorn.protocols.http',
        'uvicorn.protocols.http.auto','uvicorn.protocols.websockets','uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan','uvicorn.lifespan.server','slowapi','slowapi._version',
        'slowapi.util','slowapi.middleware','slowapi.errors','slowapi.request',
        'python_multipart','python_multipart.multipart','python_multipart.decoders',
        'rich','rich.console','rich.pretty','rich.live','rich.table',
        'rich._null_file','rich._loop','rich._utils','rich.table_columns',
        'httpx','tenacity','tenacity.before','tenacity.after','tenacity.stop',
        'tenacity.wait','requests','requests.models','requests.sessions',
        'requests.utils','requests.exceptions','requests.adapters','requests.cookies',
        'requests.auth','python_dotenv','pythonjsonlogger','pythonjsonlogger.jsonlogger',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='s2rs-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    entitlements_inherit=None,
)