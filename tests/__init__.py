from __future__ import annotations

import warnings


# Synthetic audio fixtures in our tests can be intentionally very short.
# librosa then emits n_fft sizing warnings that do not indicate a failure in
# the tested behavior, so we silence them for cleaner unittest output.
warnings.filterwarnings(
    "ignore",
    message=r"n_fft=.*too large for input signal of length=.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Trying to estimate tuning from empty frequency set\.",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module=r"librosa\.core\.spectrum",
)

# Python 3.12 surfaces deprecation warnings from audioread's raw stdlib backends
# during import; they are third-party noise for our current test suite.
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    module=r"audioread\.rawread",
)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    module=r"librosa\.core\.intervals",
)
