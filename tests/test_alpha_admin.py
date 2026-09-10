import importlib.util
import os
from pathlib import Path
import stat


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path('scripts') / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example_body():
    return Path('.env.alpha.example').read_text()


def test_init_env_generates_secret_mode_600_and_never_creates_user(tmp_path):
    admin = script('alpha_admin')
    target = tmp_path / '.env.alpha'
    example = tmp_path / '.env.alpha.example'
    example.write_text(example_body())
    created = admin.init_env(target, example=example)
    assert created == target
    text = target.read_text()
    assert 'REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS' not in text
    assert 'alpha_users' not in text
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    try:
        admin.init_env(target, example=example)
    except FileExistsError:
        pass
    else:
        raise AssertionError('init_env overwrote an existing env file')


def test_alpha_admin_localizes_env_without_shell_expansion(tmp_path):
    admin = script('alpha_admin')
    env_file = tmp_path / '.env.alpha'
    env_file.write_text(example_body().replace('REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS', 'x' * 48) + "\nLITERAL='$HOME/not-expanded'\n")
    env = admin.alpha_env(env_file, api_port='8111', web_port='3333')
    assert env['ALPHA_DATABASE_PATH'].endswith('/.alpha/alpha.sqlite3')
    assert env['LOCAL_OBJECT_ROOT'].endswith('/.alpha/objects')
    assert env['WORKER_API_BASE_URL'] == 'http://127.0.0.1:8111'
    assert env['SITE_URL'] == 'http://localhost:3333'
    assert env['LITERAL'] == '$HOME/not-expanded'
    assert admin.validate_for_admin(env) == []


def test_alpha_admin_invokes_alpha_auth_without_secret_on_command(monkeypatch, tmp_path):
    admin = script('alpha_admin')
    env_file = tmp_path / '.env.alpha'
    secret = 's' * 48
    env_file.write_text(example_body().replace('REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS', secret))
    calls = []

    def fake_run(command, *, cwd, env, check):
        calls.append((command, cwd, env, check))
        class Done:
            returncode = 0
        return Done()

    monkeypatch.setattr(admin.subprocess, 'run', fake_run)
    monkeypatch.setattr(admin.alpha_dev, 'repo_python_executable', lambda: '/repo/.venv/bin/python')
    assert admin.run_alpha_auth('create-user', email='founder@example.com', generate_password=True, env_file=env_file, api_port='8000', web_port='3000') == 0
    command, cwd, env, check = calls[0]
    assert command[:3] == ['/repo/.venv/bin/python', '-m', 'handwrite_font_maker.web.alpha_auth']
    assert 'create-user' in command
    assert '--generate-password' in command
    assert secret not in ' '.join(command)
    assert env['INTERNAL_API_KEY'] == secret
    assert check is False
