Environment Note

bot_framework intentionally has no virtual environment of its own.
It is installed editable into d4_bot's virtual environment at:
C:\Users\brian\source\repos\d4_bot\.venv

`framework.*` resolves from that shared environment, and framework tests must be run from bot_framework using:

```
C:\Users\brian\source\repos\d4_bot\.venv\Scripts\python -m pytest -q
```

Do not create a virtual environment inside bot_framework. A local bot_framework `.venv` starts empty, misses required dependencies, and framework tests will not run there.

## Capture device selection

Install hardware dependencies with `python -m pip install "bot_framework[hardware]"`.
On Windows, `list_capture_devices("dshow")` returns device indices, names and
paths. `AVerMediaCapture` requires exactly one of `device_name` (a
case-insensitive substring) or `device_index`; name selection fails if it does
not identify exactly one device. Name selection requires the Windows
`cv2_enumerate_cameras` dependency.

After warm-up, capture synchronously measures delivery over `fps_check_frames`
(default 60) and raises if achieved FPS is below `min_fps_fraction` (default
0.9) times the configured FPS. The measured `achieved_fps`, resolved device
name, path, index and `active_backend` are available as capture properties.
For index selection, the resolved name is `index <n>` and the path is `None`.

## Fill-level detection

`FillLevelDetector` in `framework.contrib.detection` accepts an `(x, y, w, h)`
ROI, an OpenCV HSV hue range (including wraparound), saturation and value
minima, a row-match fraction, a minimum consecutive-row count, and ROI-relative
full and empty calibration rows. Calling it with a BGR frame returns a
`FillLevelResult` containing the first qualifying row, its absolute frame
coordinate, and the clamped fill fraction. If no qualifying run is found, the
coordinates and fraction are `None`. The ROI must fit entirely inside the frame.
This stateless detector requires OpenCV.

## Screen-mode classification

`ScreenModeClassifier` in `framework.contrib.detection` evaluates ordered
`ModeRule` predicates against a frame, returning a `ScreenModeResult` with the
committed mode, raw mode, and true evidence names from the winning rule.
Rules require all `all_of` evidence and, when present, at least one `any_of`
item. Evidence names in the result follow `any_of` then `all_of` order.
Unlike the stateless detectors, the classifier keeps state between calls:
leaving a mode is immediate, while entering one requires the configured number
of consecutive evaluations. Call `reset()` to return to the unknown state.
