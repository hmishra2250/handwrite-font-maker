import importlib.util
from pathlib import Path
import signal


def script(name):
    import sys
    scripts = str(Path('scripts').resolve())
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(name, Path('scripts') / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_env_file(tmp_path):
    body = Path('.env.alpha.example').read_text().replace('REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS', 'x' * 48)
    path = tmp_path / '.env.alpha'
    path.write_text(body)
    return path


def test_repo_python_executable_prefers_repo_venv(tmp_path):
    alpha_dev = script('alpha_dev')
    assert alpha_dev.repo_python_executable(tmp_path, fallback='/fallback/python') == '/fallback/python'
    candidate = tmp_path / '.venv' / 'bin' / 'python'
    candidate.parent.mkdir(parents=True)
    candidate.write_text('#!/bin/sh\n')
    candidate.chmod(0o755)
    assert alpha_dev.repo_python_executable(tmp_path, fallback='/fallback/python') == str(candidate)


def test_alpha_dev_uses_repo_python_for_python_children_and_stops_on_sigterm(monkeypatch, tmp_path):
    alpha_dev = script('alpha_dev')
    env_file = valid_env_file(tmp_path)
    spawned = []
    stopped = []

    class Proc:
        def __init__(self):
            self.pid = 12345
        def poll(self):
            return None

    def fake_spawn(name, command, *, cwd, env):
        spawned.append((name, command, cwd, env))
        if name == 'web':
            raise alpha_dev.StopRequested(signal.SIGTERM)
        return Proc()

    monkeypatch.setattr(alpha_dev, 'spawn', fake_spawn)
    monkeypatch.setattr(alpha_dev, 'stop', lambda processes: stopped.extend(processes))
    monkeypatch.setattr(alpha_dev, 'repo_python_executable', lambda: '/repo/.venv/bin/python')
    code = alpha_dev.main(['--env-file', str(env_file), '--skip-worker'])
    assert code == 128 + signal.SIGTERM
    assert [name for name, *_ in spawned] == ['api', 'cleanup', 'web']
    assert spawned[0][1][0] == '/repo/.venv/bin/python'
    assert spawned[1][1][0] == '/repo/.venv/bin/python'
    assert len(stopped) == 2
