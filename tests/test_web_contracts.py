from pathlib import Path

import pytest

from handwrite_font_maker.web.api import create_job, get_job
from handwrite_font_maker.web.contracts import HardErrorCode, is_safe_font_name, is_supported_image
from handwrite_font_maker.web.job_store import JsonJobStore
from handwrite_font_maker.web.supabase_store import LocalObjectStore


def test_hard_error_taxonomy_contains_plan_codes():
    expected = {
        'MARKER_GEOMETRY_INVALID',
        'TEMPLATE_BORDER_CROPPED',
        'QR_TEMPLATE_MISMATCH',
        'RECTIFIED_PAGE_OUT_OF_BOUNDS',
        'GLYPH_GRID_NOT_FOUND',
        'GLYPH_REQUIRED_SET_MISSING',
        'FONT_VALIDATION_FAILED',
        'UPLOAD_OBJECT_TOO_LARGE',
    }
    assert expected <= {code.value for code in HardErrorCode}


def test_font_and_image_validation():
    assert is_safe_font_name('MyFont-Regular')
    assert not is_safe_font_name('bad font name with spaces')
    assert is_supported_image('image/jpeg')
    assert not is_supported_image('application/pdf')


def test_create_and_read_job_contract(tmp_path: Path):
    store = tmp_path / 'jobs.json'
    created = create_job(
        store,
        object_key='jobs/job_demo/input/original.jpg',
        content_type='image/jpeg',
        size_bytes=123,
        font_name='MyFont-Regular',
        family_name='My Font',
    )
    assert created['status'] == 'queued'
    assert created['stage'] == 'queued'
    assert created['retentionExpiresAt']
    read = get_job(store, created['jobId'])
    assert read == created


def test_create_job_rejects_raw_invalid_metadata(tmp_path: Path):
    with pytest.raises(ValueError, match='UNSUPPORTED_IMAGE_TYPE'):
        create_job(tmp_path / 'jobs.json', object_key='x', content_type='application/pdf', size_bytes=1, font_name='MyFont', family_name='My Font')
    with pytest.raises(ValueError, match='FONT_METADATA_INVALID'):
        create_job(tmp_path / 'jobs.json', object_key='x', content_type='image/png', size_bytes=1, font_name='bad font', family_name='Bad')


def test_local_object_store_uses_job_scoped_paths(tmp_path: Path):
    store = LocalObjectStore(tmp_path)
    source = tmp_path / 'source.txt'
    source.write_text('artifact', encoding='utf-8')
    store.upload_from_path('jobs/job_a/artifacts/a.txt', source, 'text/plain')
    target = tmp_path / 'target.txt'
    store.download_to_path('jobs/job_a/artifacts/a.txt', target)
    assert target.read_text(encoding='utf-8') == 'artifact'
