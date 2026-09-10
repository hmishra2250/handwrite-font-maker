"""Authenticated visual-candidate endpoint sharing capture ownership and quotas."""
from __future__ import annotations

import math
import tempfile
import threading
from pathlib import Path


_INK_SLOT = threading.BoundedSemaphore(2)

def validate_context(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {'character','baseline','threshold','invert','inkMaskMethod','foregroundMethod','foregroundStyle'}:
        raise ValueError('Invalid capture context.')
    for key, value in raw.items():
        if key == 'character' and (not isinstance(value, str) or not 1 <= len(value) <= 8):
            raise ValueError('Invalid capture character.')
        if key in {'baseline','threshold'}:
            low, high = (0,1) if key == 'baseline' else (1,254)
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Invalid capture context number.')
        if key == 'invert' and not isinstance(value, bool):
            raise ValueError('Invalid capture polarity.')
        choices = {'inkMaskMethod': {'global','adaptive'}, 'foregroundMethod': {'auto','grabcut','model','box-model'}, 'foregroundStyle': {'ink','silhouette'}}
        if key in choices and (not isinstance(value,str) or value not in choices[key]):
            raise ValueError('Invalid capture context option.')
    return raw


def handle_candidates(handler, body):
    from . import server as api
    from ..candidates import generate_candidates
    slot = None
    acquired = False
    try:
        config, auth = handler._request_context()
        photo = api._server_bound_input_photo(api.parse_input_photo(body.get('inputPhoto')), config)
        api._authorize_capture_objects(config, auth, photo, None)
        rectangle = api._validate_normalized_rectangle(body.get('rectangle'))
        stage = body.get('stage')
        if stage not in ('ink','objects'):
            raise ValueError('Choose an ink or objects candidate stage.')
        context = validate_context(body.get('context'))
        handler._capture_trace = api.start_capture_trace(auth.owner_id, {**body, 'context': context})
        slot = _INK_SLOT if stage == 'ink' else api._foreground_slot()
        acquired = slot.acquire(blocking=False)
        if not acquired:
            api._segmentation_error(handler, 'SEGMENTATION_BUSY', 'Another extraction is finishing. Your existing letter options are safe; retry shortly.', retryable=True)
            return
        api._record_preview(config, auth)
        with tempfile.TemporaryDirectory(prefix='capture_candidates_') as tmp:
            image_path = Path(tmp)/'input'
            api._object_store(handler.object_root).download_to_path(photo.object_key, image_path)
            api._validate_input_image(image_path, photo)
            if handler._capture_trace is not None:
                handler._capture_trace.source(image_path)
            result = generate_candidates(image_path, rectangle, stage)
        api._json(handler, 200, result)
    except api.SecurityError as exc:
        api._error(handler, exc.status, exc.code, exc.message)
    except (api.QuotaExceeded, api.ObjectAccessError) as exc:
        api._error(handler, exc.status, exc.code, exc.message)
    except ValueError as exc:
        api._foreground_value_error(handler, exc)
    except Exception:
        api._error(handler, 422, api.HardErrorCode.GLYPH_EXTRACTION_FAILED, 'Could not prepare letter options. Your photo is unchanged; retry or use manual refinement.')
    finally:
        if acquired:
            slot.release()
        handler._capture_trace = None
