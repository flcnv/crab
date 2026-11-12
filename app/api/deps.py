"""FastAPI dependencies. `Deps` is built once in the app lifespan (see app/api/main.py)."""

from typing import Annotated

from fastapi import Depends, Request

from app.bootstrap import Deps


def get_deps(request: Request) -> Deps:
    deps: Deps = request.app.state.deps
    return deps


DepsDep = Annotated[Deps, Depends(get_deps)]
