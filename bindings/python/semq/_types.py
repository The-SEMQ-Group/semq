"""Host representations shared by the thin adapters; no SEMQ validity rules."""
from collections.abc import Iterable
from typing import Any

import numpy as np
from numpy.typing import NDArray

Id = int | str
InputId = int | np.integer[Any] | str
IdsInput = Iterable[InputId]
IdsView = NDArray[np.uint64] | tuple[str, ...]
