from pathlib import Path
import json
import sys
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from benchmark_page_constraints import reference_crop, run


def test_reference_crop_transforms_corners_without_fabricating_pixels():
    image = np.arange(200*300*3, dtype=np.uint8).reshape(200,300,3)
    reference = np.array([[100,60],[170,60],[170,150],[100,150]], np.float32)
    crop, shifted, box = reference_crop(image, reference)
    left, top, right, bottom = box
    np.testing.assert_array_equal(crop, image[top:bottom,left:right])
    np.testing.assert_array_equal(shifted + [left,top], reference)
    assert crop.shape[0] < image.shape[0]
    assert crop.shape[1] < image.shape[1]


def test_reference_crop_stays_within_original_image():
    image = np.zeros((80,100,3),np.uint8)
    quad = np.array([[0,0],[99,0],[99,79],[0,79]],np.float32)
    crop, shifted, box = reference_crop(image,quad)
    assert box == [0,0,100,80]
    np.testing.assert_array_equal(crop,image)
    np.testing.assert_array_equal(shifted,quad)


def test_constraint_benchmark_rejects_changed_source(tmp_path):
    (tmp_path/'sample.png').write_bytes(b'changed')
    report = tmp_path/'previous.json'
    report.write_text(json.dumps({'samples':[{'sample_id':'sample','image_sha256':'0'*64}]}))
    with pytest.raises(ValueError,match='hash mismatch'):
        run(report,tmp_path,tmp_path/'out')
