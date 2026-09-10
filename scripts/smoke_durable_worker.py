#!/usr/bin/env python3
"""Disposable local PostgreSQL -> separate worker -> actual TTF/OTF canary.

Requires TEST_DATABASE_URL pointing to a disposable database plus FontForge/Potrace.
Never uses production Supabase objects or another queued job. Own test row is removed.
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from handwrite_font_maker.web.contracts import FontRequest, InputPhoto, GuidedCapture, GuidedGlyphCapture, JobStatus
from handwrite_font_maker.web.job_store import PostgresJobStore
from handwrite_font_maker.web.worker_loop import run_once
from handwrite_font_maker.web.tenant_store import PostgresTenantStore, TenantLimits


def main():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        raise SystemExit('Set TEST_DATABASE_URL to an isolated disposable database')
    os.environ.update(DATABASE_URL=url, DEPLOYMENT_MODE='local')
    os.environ.pop('SUPABASE_URL', None)
    os.environ.pop('SUPABASE_SERVICE_ROLE_KEY', None)
    store = PostgresJobStore(url)
    tenants = PostgresTenantStore(url)
    owner = str(uuid4())
    os.environ['SUPABASE_STORAGE_BUCKET'] = 'handwrite-font-jobs'
    limits = TenantLimits(10, 15 * 1024 * 1024, 10, 10, 2)
    output = Path('output/durable-worker-canary')
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='hfm-durable-canary-') as temporary:
        root = Path(temporary)
        os.environ['LOCAL_OBJECT_ROOT'] = str(root)
        key = 'canary/A.png'
        source = root / key
        source.parent.mkdir(parents=True)
        mask = Image.new('L', (256, 256), 255)
        draw = ImageDraw.Draw(mask)
        draw.polygon([(30, 215), (105, 30), (151, 30), (226, 215), (180, 215), (155, 150), (98, 150), (72, 215)], fill=0)
        draw.polygon([(115, 110), (128, 72), (142, 110)], fill=255)
        mask.save(source)
        photo = InputPhoto(object_key=key, content_type='image/png', size_bytes=source.stat().st_size)
        tenants.register_upload(owner_id=owner, bucket='handwrite-font-jobs', object_key=key, content_type='image/png', size_bytes=photo.size_bytes, limits=limits)
        tenants.mark_uploaded(owner_id=owner, bucket='handwrite-font-jobs', object_key=key, size_bytes=photo.size_bytes)
        job = tenants.create_job(owner_id=owner, input_photo=photo, font=FontRequest(font_name='DurableCanary', family_name='Durable Canary', style_name='Regular'), capture=GuidedCapture(glyphs=(GuidedGlyphCapture('A', photo, .84),)), bucket='handwrite-font-jobs', limits=limits)
        store.next_queued = lambda: store.claim(job.id)
        try:
            assert run_once(store, timeout=120)
            result = store.get(job.id)
            assert result.status == JobStatus.SUCCEEDED, result.as_response()
            artifacts = {}
            for artifact in result.artifacts:
                tenants.assert_object_access(owner_id=owner, bucket='handwrite-font-jobs', object_key=artifact.object_key)
                path = root / artifact.object_key
                assert path.is_file() and path.stat().st_size > 0
                target = output / path.name
                target.write_bytes(path.read_bytes())
                artifacts[artifact.kind] = {'bytes': path.stat().st_size, 'attemptPrefix': '/attempts/' in artifact.object_key}
            font = ImageFont.truetype(str(output / 'DurableCanary.ttf'), 96)
            proof = Image.new('RGB', (600, 160), 'white')
            ImageDraw.Draw(proof).text((20, 15), 'AAA A', font=font, fill='black')
            proof.save(output / 'proof.png')
            report = {'status': result.status.value, 'attemptCount': result.attempt_count, 'artifacts': artifacts, 'proof': str(output / 'proof.png'), 'scope': 'Real local PG + tenant registry/visibility + supervised process + Potrace/FontForge; not hosted Auth/Storage or Office evidence.'}
            (output / 'report.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        finally:
            with store._connect() as conn:
                conn.execute('delete from jobs where id=%s', (job.id,))
                conn.execute('delete from tenants where owner_id=%s', (owner,))


if __name__ == '__main__':
    main()
