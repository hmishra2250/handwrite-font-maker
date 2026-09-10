from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from handwrite_font_maker import segmentation as s


@pytest.fixture
def photo():
    image = np.full((80, 120, 3), 220, np.uint8)
    image[20:60, 30:90] = (10, 20, 30)
    return image


@pytest.mark.parametrize('kwargs', [{'method':'unknown'}, {'style':'color'}, {'threshold':True}, {'threshold':128.5}, {'threshold':0}, {'threshold':255}])
def test_invalid_options_reject_before_model(photo, kwargs, monkeypatch):
    monkeypatch.setattr(s, 'predict_slimsam', lambda *a, **k: pytest.fail('invalid request reached model'))
    with pytest.raises(ValueError):
        s.segment_image(photo, [.1,.1,.9,.9], **kwargs)


def test_auto_fallback_is_visible_and_model_explicit_fails(photo, monkeypatch):
    def missing(*a, **k):
        raise s.ModelUnavailableError('Weights missing.')
    mask = np.full(photo.shape[:2], 255, np.uint8)
    mask[25:50, 40:70] = 0
    monkeypatch.setattr(s, 'predict_slimsam', missing)
    monkeypatch.setattr(s, 'extract_foreground', lambda *a: mask)
    result = s.segment_image(photo, [.1,.1,.9,.9], points=[{'x':.5,'y':.5,'label':1}])
    assert result.method == 'grabcut' and result.model_id is None
    assert 'Weights missing' in result.warnings[0]
    with pytest.raises(s.ModelUnavailableError):
        s.segment_image(photo, [.1,.1,.9,.9], method='model', points=[{'x':.5,'y':.5,'label':1}])


def test_busy_model_does_not_trigger_extra_cpu_fallback(photo, monkeypatch):
    def busy(*a, **k):
        raise s.SegmentationBusyError('busy')
    monkeypatch.setattr(s, 'predict_slimsam', busy)
    monkeypatch.setattr(s, 'extract_foreground', lambda *a: pytest.fail('busy fallback'))
    with pytest.raises(s.SegmentationBusyError):
        s.segment_image(photo, [.1,.1,.9,.9], points=[{'x':.5,'y':.5,'label':1}])


def test_ink_style_intersects_cutout_without_filling_holes(photo, monkeypatch):
    mask = np.zeros(photo.shape[:2], np.uint8)
    mask[35:40, 50:55] = 255
    monkeypatch.setattr(s, 'predict_slimsam', lambda *a, **k: mask)
    result = s.segment_image(photo, [.1,.1,.9,.9], method='model', style='ink', threshold=128, points=[{'x':.5,'y':.5,'label':1}])
    assert result.method == 'slimsam' and result.model_id.startswith(s.MODEL_REPO)
    assert result.mask[30,40] == 0 and result.mask[37,52] == 255
    assert result.mask[0,0] == 255


def test_preprocessing_rgb_scale_and_normalized_padding():
    image = np.zeros((40,80,3), np.uint8)
    image[:,:,2] = 255
    pixels, shape = s._encode_image(image)
    assert shape == (512,1024)
    assert pixels.shape == (1,3,1024,1024) and pixels.dtype == np.float32
    assert np.isclose(pixels[0,0,0,0], (1-.485)/.229)
    assert np.all(pixels[:,:,512:] == 0)


def test_prediction_maps_point_prompts_and_restores_full_frame(photo, monkeypatch):
    class Encoder:
        def get_outputs(self):
            return [SimpleNamespace(name=x) for x in ('image_embeddings','image_positional_embeddings')]
        def run(self, names, inputs):
            assert inputs['pixel_values'].shape == (1,3,1024,1024)
            return [np.zeros((1,256,64,64),np.float32)]*2
    class Decoder:
        def get_inputs(self):
            return [SimpleNamespace(name=x) for x in ('input_points','input_labels','image_embeddings','image_positional_embeddings')]
        def get_outputs(self):
            return [SimpleNamespace(name=x) for x in ('iou_scores','pred_masks')]
        def run(self, names, inputs):
            assert inputs['input_labels'].tolist() == [[[1,0]]]
            assert inputs['input_points'].shape == (1,1,2,2)
            assert np.isclose(inputs['input_points'][0,0,0,0], .1*1024)
            masks = np.full((1,1,3,256,256), -10, np.float32)
            masks[:,:,1] = 10
            return [np.array([[[.1,.9,.2]]]), masks]
    monkeypatch.setattr(s, '_sessions', lambda variant: (Encoder(),Decoder()))
    result = s.predict_slimsam(photo,[.1,.1,.9,.9],points=[{'x':.1,'y':.1,'label':1},{'x':.9,'y':.9,'label':0}])
    assert result.shape == photo.shape[:2]
    assert result[40,60] == 0 and result[0,0] == 255
    assert not s._INFERENCE_LOCK.locked()


def test_missing_and_corrupt_weights_are_not_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv('HANDWRITE_MODEL_DIR',str(tmp_path))
    with pytest.raises(s.ModelUnavailableError):
        s._sessions('fp32')
    name = s.model_files('fp32')[0]
    path = tmp_path/name
    path.write_bytes(b'bad')
    with pytest.raises(s.ModelUnavailableError):
        s.verify_asset(path)


@pytest.mark.parametrize('rect', [[0,0,0,1], [False,.1,.9,.9], [float('nan'),.1,.9,.9]])
def test_bad_rectangle(photo, rect):
    with pytest.raises(ValueError):
        s.predict_slimsam(photo,rect)


def test_explicit_model_requires_foreground_point(photo):
    with pytest.raises(ValueError, match='keep point'):
        s.segment_image(photo, [.1,.1,.9,.9], method='model')


@pytest.mark.parametrize('points', [[{'x':.5,'y':.5,'label':True}], [{'x':.5,'y':.5,'label':2}], [{'x':0,'y':0,'label':1}], [{'x':float('nan'),'y':.5,'label':1}], [{}]*17])
def test_invalid_model_points(photo, points):
    with pytest.raises(ValueError):
        s.segment_image(photo, [.1,.1,.9,.9], points=points)


def test_box_model_dispatch_uses_efficientsam_metadata_without_points(photo, monkeypatch):
    import handwrite_font_maker.efficient_segmentation as efficient

    mask = np.full(photo.shape[:2], 255, np.uint8)
    mask[25:50, 40:70] = 0
    calls = {}

    def fake_predict(image, rectangle):
        calls['shape'] = image.shape
        calls['rectangle'] = rectangle
        return mask

    monkeypatch.setattr(efficient, 'predict_efficientsam_box', fake_predict)
    result = s.segment_image(photo, [.1, .1, .9, .9], method='box-model')
    assert result.method == 'efficientsam'
    assert result.model_id == f'{efficient.MODEL_REPO}@{efficient.MODEL_REVISION}:ti-box'
    assert result.warnings == ()
    assert np.array_equal(result.mask, mask)
    assert calls['shape'] == photo.shape
    assert calls['rectangle'] == (.1, .1, .9, .9)


def test_box_model_rejects_points_before_model(photo, monkeypatch):
    import handwrite_font_maker.efficient_segmentation as efficient

    monkeypatch.setattr(efficient, 'predict_efficientsam_box', lambda *a, **k: pytest.fail('box-model with points reached model'))
    with pytest.raises(ValueError, match='omit'):
        s.segment_image(photo, [.1, .1, .9, .9], method='box-model', points=[{'x': .5, 'y': .5, 'label': 1}])
    with pytest.raises(ValueError, match='omit'):
        s.segment_image(photo, [.1, .1, .9, .9], method='box-model', points=())


def test_auto_without_positive_point_still_uses_grabcut(photo, monkeypatch):
    monkeypatch.setattr(s, 'predict_slimsam', lambda *a, **k: pytest.fail('auto without positive point reached SlimSAM'))
    mask = np.full(photo.shape[:2], 255, np.uint8)
    mask[25:50, 40:70] = 0
    monkeypatch.setattr(s, 'extract_foreground', lambda *a: mask)
    result = s.segment_image(photo, [.1, .1, .9, .9], method='auto')
    assert result.method == 'grabcut'
    assert result.model_id is None
    assert 'GrabCut' in result.warnings[0]


def test_efficientsam_prediction_maps_box_prompt_and_releases_shared_lock(photo, monkeypatch):
    import handwrite_font_maker.efficient_segmentation as efficient

    class Encoder:
        def run(self, names, inputs):
            assert names is None
            assert inputs['batched_images'].shape == (1, 3, 80, 120)
            assert inputs['batched_images'].dtype == np.float32
            return [np.zeros((1, 256, 64, 64), np.float32)]

    class Decoder:
        def run(self, names, inputs):
            assert names is None
            assert inputs['batched_point_labels'].tolist() == [[[2.0, 3.0]]]
            assert inputs['batched_point_coords'].shape == (1, 1, 2, 2)
            assert np.isclose(inputs['batched_point_coords'][0, 0, 0, 0], .1 * 120)
            assert np.isclose(inputs['batched_point_coords'][0, 0, 1, 1], .9 * 80)
            assert inputs['orig_im_size'].tolist() == [80, 120]
            masks = np.full((1, 1, 3, 80, 120), -10, np.float32)
            masks[:, :, 1, 20:60, 30:90] = 10
            return [masks, np.array([[[.1, .9, .2]]], dtype=np.float32)]

    monkeypatch.setattr(efficient, '_sessions', lambda: (Encoder(), Decoder()))
    result = efficient.predict_efficientsam_box(photo, [.1, .1, .9, .9])
    assert result.shape == photo.shape[:2]
    assert result.dtype == np.uint8
    assert result[40, 60] == 0 and result[0, 0] == 255
    assert not s._INFERENCE_LOCK.locked()


def test_efficientsam_sessions_share_bounded_model_cache(tmp_path, monkeypatch):
    import handwrite_font_maker.efficient_segmentation as efficient

    efficient.MODEL_CACHE.clear()
    efficient.MODEL_CACHE[('slimsam', 'old')] = ('old_encoder', 'old_decoder')
    for name, (size, _digest) in efficient.MODEL_ASSETS.items():
        (tmp_path / name).write_bytes(b'x' * size)
    monkeypatch.setenv('HANDWRITE_EFFICIENTSAM_MODEL_DIR', str(tmp_path))
    monkeypatch.setattr(efficient, 'verify_asset', lambda path: None)

    class Options:
        intra_op_num_threads = 0
        inter_op_num_threads = 0

    class Ort:
        SessionOptions = Options

        @staticmethod
        def InferenceSession(path, sess_options, providers):
            return path

    monkeypatch.setitem(__import__('sys').modules, 'onnxruntime', Ort)
    sessions = efficient._sessions()
    assert len(efficient.MODEL_CACHE) == 1
    assert sessions == tuple(str(tmp_path / name) for name in efficient.MODEL_ASSETS)
    assert next(iter(efficient.MODEL_CACHE))[0] == 'efficientsam'
