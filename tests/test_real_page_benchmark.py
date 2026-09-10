import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from benchmark_real_pages import quad_metrics, summarize


def test_page_metrics_cyclic_alignment_and_overlap():
    quad = np.array([[10,10],[90,10],[90,90],[10,90]],np.float32)
    result = quad_metrics(np.roll(quad, 1, axis=0),quad,(100,100))
    assert result['polygon_iou'] == pytest.approx(1)
    assert result['corner_rmse_px_cyclic'] == 0
    assert quad_metrics(quad+200,quad,(300,300))['polygon_iou'] == 0


def test_rejected_pages_stay_in_accuracy_denominator():
    result = summarize([{'status':'rejected'}, {'status':'detected','metrics':{'polygon_iou':1}}])
    assert result['frames'] == 2
    assert result['mean_iou_all_frames_rejections_zero'] == .5
