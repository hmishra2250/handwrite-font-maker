import base64
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np
import pytest
from PIL import Image

from handwrite_font_maker.candidates import generate_candidates, ink_masks, vector_candidate
from handwrite_font_maker.web.candidate_http import validate_context


def letter(light=True):
    image = np.full((200, 160, 3), 0 if light else 255, np.uint8)
    color = (255,)*3 if light else (0,)*3
    cv2.putText(image, 'A', (30,150), cv2.FONT_HERSHEY_SIMPLEX, 3, color, 8, cv2.LINE_AA)
    return image


@pytest.mark.parametrize('light',[True,False])
def test_auto_polarity_retains_letter_hole_and_excludes_outside(light):
    image, options = ink_masks(letter(light), [.1,.1,.9,.9])
    for name, mask, polarity in options[:2]:
        assert polarity == ('light-on-dark' if light else 'dark-on-light')
        assert .01 < (mask < 128).mean() < .3
        assert np.all(mask[:20] == 255)
        count, hierarchy = cv2.findContours((mask<128).astype('uint8'), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        assert hierarchy is not None and any(h[3] != -1 for h in hierarchy[0]), name


@pytest.mark.skipif(not shutil.which('potrace'), reason='potrace unavailable')
def test_candidates_are_real_svg_paths_and_masks(tmp_path):
    path = tmp_path/'input.png'; Image.fromarray(letter()).save(path)
    result = generate_candidates(path, [.1,.1,.9,.9], 'ink')
    assert len(result['candidates']) >= 2
    for candidate in result['candidates']:
        svg = base64.b64decode(candidate['svgDataUrl'].split(',')[1])
        assert b'<path' in svg and b'<image' not in svg
        assert base64.b64decode(candidate['maskDataUrl'].split(',')[1]).startswith(b'\x89PNG')


def test_blank_mask_rejected():
    with pytest.raises(ValueError):
        vector_candidate(np.full((32,32),255,np.uint8),name='blank',label='Blank',method='test')


def test_slow_methods_have_hard_subprocess_deadline(monkeypatch,tmp_path):
    path=tmp_path/'input.png'; Image.fromarray(letter()).save(path)
    calls=[]
    def timeout(args,**kwargs):
        calls.append(kwargs['timeout'])
        raise subprocess.TimeoutExpired(args,kwargs['timeout'])
    monkeypatch.setattr('handwrite_font_maker.candidates.subprocess.run',timeout)
    result=generate_candidates(path,[.1,.1,.9,.9],'objects')
    assert calls == [25,25,25]
    assert not result['candidates'] and len(result['failures'])==3


@pytest.mark.parametrize('raw',[{'password':'no'},{'baseline':float('nan')},{'invert':'true'},{'character':''},{'threshold':999}])
def test_context_rejects_unbounded_or_unrelated_fields(raw):
    with pytest.raises(ValueError): validate_context(raw)


@pytest.mark.skipif(not shutil.which('potrace'), reason='potrace unavailable')
def test_candidate_normalization_preserves_pixels_and_sets_useful_font_size():
    from io import BytesIO
    mask=np.full((1024,768),255,np.uint8)
    cv2.putText(mask,'A',(300,650),cv2.FONT_HERSHEY_SIMPLEX,7,0,14,cv2.LINE_8)
    result=vector_candidate(mask,name='clean',label='Clean',method='test')
    normalized=np.asarray(Image.open(BytesIO(base64.b64decode(result['maskDataUrl'].split(',')[1]))))
    assert np.count_nonzero(normalized<128)==np.count_nonzero(mask<128)
    ys,_=np.where(normalized<128)
    assert .68 <= (ys.max()-ys.min()+1)/normalized.shape[0] <= .72
    assert abs((ys.max()+1)/normalized.shape[0]-.8)<.01
    assert result['provenance']['normalization']['resampled'] is False


@pytest.mark.skipif(not shutil.which('potrace'), reason='potrace unavailable')
def test_large_image_records_coordinate_frames(tmp_path):
    image=cv2.resize(letter(),(1600,2000))
    path=tmp_path/'large.png'; Image.fromarray(image).save(path)
    result=generate_candidates(path,[.1,.1,.9,.9],'ink')
    for candidate in result['candidates']:
        provenance=candidate['provenance']
        assert provenance['originalSourceSize']==[1600,2000]
        assert provenance['processingSourceSize']==[819,1024]
        assert provenance['maskSize']==[candidate['width'],candidate['height']]
        assert provenance['processingScale']==[819/1600,1024/2000]


def test_pure_binary_light_ink_with_zero_otsu_cutoff():
    image=letter(light=True)
    image=np.where(image>127,255,0).astype(np.uint8)
    _,options=ink_masks(image,[.1,.1,.9,.9])
    assert options[0][2]=='light-on-dark'
    assert .01 < (options[0][1]<128).mean() < .3
