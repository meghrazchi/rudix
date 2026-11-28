from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

WebVitalName = Literal["LCP", "INP", "CLS", "FCP", "TTFB"]
WebVitalRating = Literal["good", "needs-improvement", "poor"]
WebVitalNavigationType = Literal[
    "navigate",
    "reload",
    "back-forward",
    "back-forward-cache",
    "prerender",
    "restore",
]

# A route pattern, never a concrete URL: no query string, no dots, no colons.
WebVitalRoute = Annotated[
    str,
    StringConstraints(pattern=r"^/[A-Za-z0-9\[\]_/-]{0,120}$"),
]

MAX_TIMING_VALUE_MS = 60_000.0
MAX_CLS_VALUE = 10.0
MAX_SAMPLES_PER_REQUEST = 10


class WebVitalSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: WebVitalName
    value: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    route: WebVitalRoute
    rating: WebVitalRating
    navigation_type: WebVitalNavigationType | None = None

    @model_validator(mode="after")
    def _check_value_range(self) -> Self:
        limit = MAX_CLS_VALUE if self.name == "CLS" else MAX_TIMING_VALUE_MS
        if self.value > limit:
            raise ValueError(f"value for {self.name} must be at most {limit:g}")
        return self


class WebVitalsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: Annotated[
        list[WebVitalSample],
        Field(min_length=1, max_length=MAX_SAMPLES_PER_REQUEST),
    ]
