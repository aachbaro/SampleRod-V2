# SampleRod Animation Module

This repository contains a sample Qt application. The new `AnimationHelper`
module located in `frontend/animation.py` centralises fade and size
animations. Widgets can use it as follows:

```python
from frontend.animation import AnimationHelper
AnimationHelper.fade_in(widget, duration=300)
AnimationHelper.fade_out(widget)
AnimationHelper.animate_height(widget, 0, 200)
```

The helper keeps a reference to running animations to avoid them being
collected. The SampleCard, WaveformWidget and MarkerListWidget now use this
module for their visual effects.
