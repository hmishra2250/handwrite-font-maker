from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_vercel_routes_do_not_shell_out_or_import_python_pipeline():
    api_root = PROJECT_ROOT / 'web' / 'app' / 'api'
    assert api_root.exists()
    forbidden = ['child_process', 'spawn(', 'exec(', 'fontforge', 'potrace', 'build_font', 'handwrite_font_maker']
    for path in api_root.rglob('*.ts'):
        source = path.read_text(encoding='utf-8')
        for token in forbidden:
            assert token not in source, f'{path} contains forbidden token {token}'


def test_vercel_routes_do_not_return_binary_responses_except_local_object_proxy():
    object_proxy = PROJECT_ROOT / 'web' / 'app' / 'api' / 'objects' / '[...key]' / 'route.ts'
    for path in (PROJECT_ROOT / 'web' / 'app' / 'api').rglob('*.ts'):
        source = path.read_text(encoding='utf-8')
        assert 'arrayBuffer' not in source
        assert 'ReadableStream' not in source
        if path != object_proxy:
            assert 'application/octet-stream' not in source
