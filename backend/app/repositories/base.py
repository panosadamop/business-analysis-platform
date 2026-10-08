"""Thin repository helpers over Motor.

Documents are stored with ``_id`` holding the domain id. Models never see the
Mongo specific key. Mutations carry an optimistic concurrency token (``rev``).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Iterable, Sequence, Type, TypeVar

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from app.core.errors import NotFound, VersionConflict
from app.core.utils import utcnow
from app.db.mongo import col
from app.models.common import Doc

M = TypeVar("M", bound=Doc)


def encode(value: Any) -> Any:
    """Make a value BSON safe.

    Calendar dates are stored as ISO strings so they sort and compare correctly
    and round trip back into ``datetime.date`` through the models. Decimals are
    stored as strings to keep money exact (section 18).
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def to_doc(model: Doc) -> dict[str, Any]:
    data = encode(model.model_dump(by_alias=True, mode="python"))
    data["_id"] = data.pop("id")
    return data


def from_doc(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    out = dict(data)
    if "_id" in out:
        out["id"] = out.pop("_id")
    return out


class Repo(Generic[M]):
    def __init__(self, collection: str, model: Type[M]) -> None:
        self.name = collection
        self.model = model

    @property
    def c(self) -> AsyncIOMotorCollection:
        return col(self.name)

    # --- reads -------------------------------------------------------------
    async def get(self, doc_id: str, **scope: Any) -> M | None:
        query: dict[str, Any] = {"_id": doc_id, **scope}
        data = from_doc(await self.c.find_one(query))
        return self.model(**data) if data else None

    async def require(self, doc_id: str, **scope: Any) -> M:
        found = await self.get(doc_id, **scope)
        if not found:
            raise NotFound(f"{self.name} {doc_id} not found")
        return found

    async def find_one(self, query: dict[str, Any]) -> M | None:
        data = from_doc(await self.c.find_one(query))
        return self.model(**data) if data else None

    async def list(self, query: dict[str, Any] | None = None, *,
                   sort: Sequence[tuple[str, int]] | None = None,
                   limit: int = 0, offset: int = 0) -> list[M]:
        cursor = self.c.find(query or {})
        if sort:
            cursor = cursor.sort(list(sort))
        if offset:
            cursor = cursor.skip(offset)
        if limit:
            cursor = cursor.limit(limit)
        return [self.model(**from_doc(d)) for d in await cursor.to_list(length=limit or None)]

    async def count(self, query: dict[str, Any] | None = None) -> int:
        return await self.c.count_documents(query or {})

    async def exists(self, query: dict[str, Any]) -> bool:
        return await self.c.count_documents(query, limit=1) > 0

    # --- writes ------------------------------------------------------------
    async def insert(self, model: M) -> M:
        await self.c.insert_one(to_doc(model))
        return model

    async def insert_many(self, models: Iterable[M]) -> int:
        docs = [to_doc(m) for m in models]
        if not docs:
            return 0
        await self.c.insert_many(docs)
        return len(docs)

    async def replace(self, model: M) -> M:
        model.updated_at = utcnow()
        model.rev += 1
        doc = to_doc(model)
        await self.c.replace_one({"_id": model.id}, doc, upsert=True)
        return model

    async def update(self, doc_id: str, changes: dict[str, Any], *,
                     expected_rev: int | None = None, **scope: Any) -> M:
        """Apply a partial update. A mismatched ``expected_rev`` is a conflict."""
        query: dict[str, Any] = {"_id": doc_id, **scope}
        if expected_rev is not None:
            query["rev"] = expected_rev
        changes = encode(dict(changes))
        changes["updatedAt"] = utcnow()
        updated = await self.c.find_one_and_update(
            query, {"$set": changes, "$inc": {"rev": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            if expected_rev is not None and await self.exists({"_id": doc_id}):
                raise VersionConflict(
                    "The record changed while you were editing it",
                    details={"id": doc_id, "expectedRev": expected_rev},
                )
            raise NotFound(f"{self.name} {doc_id} not found")
        return self.model(**from_doc(updated))

    async def raw_update(self, query: dict[str, Any], operation: dict[str, Any]) -> int:
        result = await self.c.update_many(encode(query), encode(operation))
        return result.modified_count

    async def delete(self, doc_id: str, **scope: Any) -> bool:
        result = await self.c.delete_one({"_id": doc_id, **scope})
        return result.deleted_count > 0

    async def delete_many(self, query: dict[str, Any]) -> int:
        result = await self.c.delete_many(query)
        return result.deleted_count

    async def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self.c.aggregate(pipeline).to_list(length=None)
