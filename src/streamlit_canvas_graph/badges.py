"""Application-specific badges using the component's primitive renderer API."""

from collections.abc import Mapping, Sequence

from streamlit_graph_canvas import BadgeContext, Prim, RectPrim, TextPrim

DIRECT_BADGE_KIND = "streamlit-canvas-graph/app/direct"


class DirectBadgeRenderer:
    kind = DIRECT_BADGE_KIND
    renderer_api = 1

    def render(
        self, data: object, options: Mapping[str, object], context: BadgeContext
    ) -> Sequence[Prim]:
        if not data:
            return ()
        return (
            RectPrim(0, 0, context.width, context.height, "accent", 8),
            TextPrim(context.width / 2, context.height / 2 + 4, "Direct", "on_accent"),
        )
