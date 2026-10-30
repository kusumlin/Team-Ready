"""Load the synthetic company: docs, people, the new hire, policies and events."""
import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from .config import DATA_DIR


@dataclass(frozen=True)
class Passage:
    doc_id: str
    index: int
    text: str

    @property
    def ref(self) -> str:
        return f"{self.doc_id}#{self.index}"


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    owner: str
    team: str
    updated_at: date
    region: str
    body: str
    passages: tuple[Passage, ...] = field(default=())


def _parse_doc(text: str) -> Doc:
    header, _, body = text.partition("\n---\n")
    meta = {}
    for line in header.splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    body = body.strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    passages = tuple(Passage(meta["id"], i, line) for i, line in enumerate(lines))
    return Doc(
        id=meta["id"],
        title=meta["title"],
        owner=meta["owner"],
        team=meta["team"],
        updated_at=date.fromisoformat(meta["updated_at"]),
        region=meta.get("region", "global"),
        body=body,
        passages=passages,
    )


@lru_cache(maxsize=1)
def load_docs() -> dict[str, Doc]:
    docs = {}
    for path in sorted((DATA_DIR / "docs").glob("*.md")):
        doc = _parse_doc(path.read_text())
        docs[doc.id] = doc
    return docs


@lru_cache(maxsize=1)
def load_people() -> dict[str, dict]:
    return {p["id"]: p for p in json.loads((DATA_DIR / "people.json").read_text())}


@lru_cache(maxsize=1)
def _local_user() -> dict:
    return json.loads((DATA_DIR / "user.json").read_text())


def load_user() -> dict:
    """The new hire. With Workday configured, name, title, org and work email come
    from the Workday development tenant; everything else stays local."""
    from . import workday

    user = dict(_local_user())
    wd = workday.profile()
    if wd:
        user.update({k: v for k, v in wd.items() if v})
        user["profile_source"] = "Workday"
    else:
        user["profile_source"] = "local"
    return user


@lru_cache(maxsize=1)
def load_policies() -> dict:
    return json.loads((DATA_DIR / "policies.json").read_text())


def load_events() -> list[dict]:
    path = DATA_DIR / "events.json"
    return json.loads(path.read_text()) if path.exists() else []
