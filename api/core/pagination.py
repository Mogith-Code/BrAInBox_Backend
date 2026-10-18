"""Page-based pagination.

Usage:
    @router.get("/things", response_model=Page[ThingOut])
    async def list_things(paging: PageParamsDep, session: SessionDep):
        items, total = await service.list_things(session, offset=paging.offset, limit=paging.size)
        return Page.create(items, total, paging)
"""

import math
from typing import Annotated, Generic, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = 1
    size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def get_page_params(
    page: Annotated[int, Query(ge=1, description="Page number, starting at 1")] = 1,
    size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> PageParams:
    return PageParams(page=page, size=size)


PageParamsDep = Annotated[PageParams, Depends(get_page_params)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def create(cls, items: list[T], total: int, params: PageParams) -> "Page[T]":
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=math.ceil(total / params.size) if total else 0,
        )
