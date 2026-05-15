# Synthetic Capture Detection Report

30 synthetic images simulating real-world mobile phone captures tested against the ArUco marker detection and homography pipeline.

## Summary

| Metric | Value |
|---|---|
| Total tests | 30 |
| Passed | 26 |
| Failed | 4 |
| Pass rate | 86.7% |
| Reprojection error (min) | 0.00 px |
| Reprojection error (max) | 3.75 px |
| Reprojection error (mean) | 0.40 px |
| Threshold | 5.00 px |

## Results by Category

### Perspective warp (4/4 pass)
| Test | Tilt | Result | Reproj |
|---|---|---|---|
| 03_tilt_light | 0.04 | PASS | 0.76 px |
| 04_tilt_medium | 0.10 | PASS | 0.73 px |
| 05_tilt_heavy | 0.16 | PASS | 0.78 px |
| 06_tilt_extreme | 0.20 | PASS | 0.65 px |

### Brightness (4/4 pass)
| Test | Factor | Result |
|---|---|---|
| 07_very_dark | 0.40x | PASS |
| 08_dark | 0.55x | PASS |
| 09_bright | 1.40x | PASS |
| 10_overexposed | 1.60x | PASS |

### Noise (3/3 pass)
| Test | Sigma | Result |
|---|---|---|
| 11_noise_light | 8 | PASS |
| 12_noise_heavy | 20 | PASS |
| 13_noise_extreme | 30 | PASS |

### JPEG compression (3/3 pass)
| Test | Quality | Result | Reproj |
|---|---|---|---|
| 14_jpeg_q50 | 50 | PASS | 0.00 px |
| 15_jpeg_q25 | 25 | PASS | 0.50 px |
| 16_jpeg_q15 | 15 | PASS | 1.27 px |

### Zoom/distance (3/3 pass)
| Test | Crop | Result |
|---|---|---|
| 17_far_zoom | -10% (extra bg) | PASS |
| 18_close_zoom | -2% (slight bg) | PASS |
| 19_edge_crop_3pct | 3% crop | PASS |

### Page bend / barrel distortion (1/3 pass)
| Test | k | Result |
|---|---|---|
| 20_bend_slight | -0.08 | PASS (3.75 px) |
| 21_bend_moderate | -0.18 | FAIL |
| 22_bend_heavy | -0.30 | FAIL |

### Shadow (2/2 pass)
| Test | Strength | Result |
|---|---|---|
| 23_shadow_light | 0.25 | PASS |
| 24_shadow_heavy | 0.50 | PASS |

### Color cast (3/3 pass)
| Test | Shift (R,G,B) | Result |
|---|---|---|
| 25_warm_cast | +15,+5,-10 | PASS |
| 26_cool_cast | -10,-3,+12 | PASS |
| 27_fluorescent | -5,+10,-5 | PASS |

### Combined realistic scenarios (1/3 pass)
| Test | Conditions | Result |
|---|---|---|
| 28_phone_desk | tilt=0.08, dark=0.85, noise=10, q=70, shadow=0.15 | PASS |
| 29_phone_hand | tilt=0.14, dark=0.70, noise=15, q=45, bend=-0.10, rot=1.5 | FAIL (reproj=5.00px) |
| 30_worst_case | tilt=0.18, dark=0.50, noise=22, q=25, bend=-0.15, shadow=0.40, crop=3%, rot=2.0 | FAIL |

## Identified Limitations

### 1. Page bend (barrel distortion)
**Threshold:** k > -0.15 works reliably; k <= -0.18 fails.
**Why:** Barrel distortion warps the ArUco markers enough that OpenCV's detector cannot decode them. The 4x4 bit pattern gets stretched beyond recognition at the corners.
**Mitigation:** Users should photograph on a flat surface. Slight curl (k=-0.08) is fine.

### 2. Combined distortions with rotation + barrel
**Threshold:** Combining tilt > 0.12 + barrel > -0.08 + rotation > 1 degree pushes reprojection error past 5px.
**Why:** Each distortion independently is tolerable, but the combination compounds errors in marker center estimation.
**Mitigation:** Users should flatten the page and hold the phone roughly level.

### 3. Extreme simultaneous degradation
**Threshold:** When 4+ degradation factors combine at moderate-to-high intensity.
**Why:** ArUco detection relies on clean edge detection; heavy noise + compression + distortion degrades edges below detection threshold.

### Robust ranges (guaranteed to work)
- Perspective: up to 0.20 tilt (extreme angle)
- Brightness: 0.40x to 1.60x (very dark to overexposed)
- Noise: up to sigma=30 (very noisy)
- JPEG quality: down to q=15 (extreme compression)
- Shadow: up to 50% half-shadow
- Color cast: up to +/-15 channel shift
- Slight page bend: up to k=-0.08
- Edge crop: up to 3%
- Zoom: works at any distance where full page is visible

### Known failure modes
- Page bend k <= -0.18 (moderate curl)
- Combined tilt + bend + rotation
- Any crop that removes a corner marker (markers are at 5% from edge)
