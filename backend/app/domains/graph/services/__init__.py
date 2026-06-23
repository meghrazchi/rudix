__all__ = ["GraphService"]


def __getattr__(name: str) -> object:
    if name == "GraphService":
        from app.domains.graph.services.graph_service import GraphService

        return GraphService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
