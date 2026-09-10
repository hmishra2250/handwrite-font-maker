"""Keep the operator handoff linked and private state out of build contexts."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_handoff_local_document_links_exist():
    for name in ('README.md', 'docs/PRIVATE-ALPHA.md', 'docs/ML-SEGMENTATION.md', 'docs/DEPLOYMENT.md'):
        document = ROOT / name
        for target in re.findall(r'\]\(([^)]+)\)', document.read_text()):
            if '://' in target or target.startswith(('#', 'mailto:')):
                continue
            assert (document.parent / target.split('#')[0]).exists(), (name, target)


def test_docker_context_excludes_private_state_and_preview_builds():
    patterns = set((ROOT / '.dockerignore').read_text().splitlines())
    assert {'.alpha', '.models', 'backups', '.env.*', 'web/.next-phone', 'web/.next-mobile', 'web/.next-e2e/', 'web/.next-alpha-e2e/'} <= patterns


def test_alpha_api_resource_overrides_are_documented_and_available():
    compose = (ROOT / 'docker-compose.alpha.yml').read_text()
    example = (ROOT / '.env.alpha.example').read_text()
    readme = (ROOT / 'README.md').read_text()
    assert '${ALPHA_API_MEMORY_LIMIT:-4g}' in compose
    assert '${ALPHA_API_CPUS:-2.0}' in compose
    for key in ('ALPHA_API_MEMORY_LIMIT', 'ALPHA_API_CPUS'):
        assert key + '=' in example
        assert key + '=' in readme
