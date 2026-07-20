# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
_SOURCE_DIR = Path(SPEC).resolve().parent
_RUNTIME_SOURCE_FILES = (
    'api_models.py',
    'archive_security.py',
    'desktop_entry.py',
    'disk_reclamation.py',
    'grounding.py',
    'gunicorn_conf.py',
    'investigation.py',
    'investigation_flows.py',
    'migrations_runner.py',
    'monitoring.py',
    'parsers.py',
    'processing_lifecycle.py',
    'product_features.py',
    'query_tracer.py',
    'rollback_runner.py',
    's3_client.py',
    'server.py',
    'storage.py',
    'superchecker.py',
    'units.py',
    'validators.py',
)
_MIGRATION_SOURCE_FILES = (
    '001_add_recommendations_metadata.py',
)


def _collect_backend_datas():
    datas = []
    for filename in _RUNTIME_SOURCE_FILES:
        path = _SOURCE_DIR / filename
        if path.is_file():
            datas.append((str(path), 'backend'))

    migrations_dir = _SOURCE_DIR / 'migrations'
    for filename in _MIGRATION_SOURCE_FILES:
        path = migrations_dir / filename
        if path.is_file():
            datas.append((str(path), 'backend/migrations'))

    for package_name in ('services', 'local_ai'):
        package_dir = _SOURCE_DIR / package_name
        for path in sorted(package_dir.glob('*.py')):
            datas.append((str(path), f'backend/{package_name}'))

    return datas


a = Analysis(
    ['desktop_entry.py'],
    pathex=[str(_SOURCE_DIR)],
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
        'aiofiles',
        'uvicorn',
        'uvicorn.importer',
        'uvicorn.config',
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
        'pydantic.main',
        'pydantic.config',
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
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'fastapi.openapi',
        'fastapi.openapi.utils',
        'fastapi.openapi.docs',
        'product_features',
        'api_models',
        'archive_security',
        'services.analysis_jobs',
        'services.isolated_parser',
        'local_ai.service',
        'local_ai.models',
        'local_ai.prompts',
        'local_ai.providers',
        'disk_reclamation',
        'units',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pandas',
        'numpy',
        'boto3',
        'botocore',
        's3transfer',
        'PIL',
        'fsspec',
        'gunicorn',
        'tqdm',
        'typer',
        'pytest',
        'unittest',
    ],
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
