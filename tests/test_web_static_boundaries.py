from pathlib import Path


def test_vercel_routes_do_not_shell_out_or_import_python_pipeline():
    api_root = Path('web/app/api')
    assert api_root.exists()
    forbidden = ['child_process', 'spawn(', 'exec(', 'fontforge', 'potrace', 'build_font', 'handwrite_font_maker']
    for path in api_root.rglob('*.ts'):
        source = path.read_text(encoding='utf-8')
        for token in forbidden:
            assert token not in source, f'{path} contains forbidden token {token}'


def test_vercel_routes_do_not_return_binary_responses():
    for path in Path('web/app/api').rglob('*.ts'):
        source = path.read_text(encoding='utf-8')
        assert 'arrayBuffer' not in source
        assert 'ReadableStream' not in source
        assert 'application/octet-stream' not in source
