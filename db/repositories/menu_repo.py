"""MenuItem repository."""

from __future__ import annotations

from sqlalchemy import Numeric, String, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from db.models.menu import MenuItem

# Text columns where keyword matches should look.
_KEYWORD_COLUMNS = (
    MenuItem.id,
    MenuItem.name,
    MenuItem.description,
    MenuItem.how_its_made,
    MenuItem.taste_profile,
    MenuItem.category,
    MenuItem.spice_level,
)


def _token_conditions(tokens: list[str]):
    """Build OR conditions matching each token against any keyword column or dietary tag."""
    clauses = []
    for t in tokens:
        like = f"%{t}%"
        col_clauses = [c.ilike(like) for c in _KEYWORD_COLUMNS]
        # dietary is JSONB array; cast-to-text + ilike is the simplest
        # cross-version match that handles `["vegan"]` and the like.
        col_clauses.append(cast(MenuItem.dietary, String).ilike(like))
        clauses.append(or_(*col_clauses))
    return clauses


class MenuRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, item_id: str) -> MenuItem | None:
        return self.db.get(MenuItem, item_id)

    def list_all(self, include_unavailable: bool = False) -> list[MenuItem]:
        q = self.db.query(MenuItem)
        if not include_unavailable:
            q = q.filter(MenuItem.available == True)  # noqa: E712
        return q.order_by(MenuItem.category, MenuItem.id).all()

    def find_by_name(self, query: str) -> list[MenuItem]:
        """Back-compat shim; kept for any caller. Prefer search_keywords."""
        return self.search_keywords(query)

    # Per-field weights — structured fields count for much more than prose.
    # A hit in `spice_level=medium-hot` should outrank "Not spicy at all"
    # mentioned inside a description.
    _FIELD_WEIGHTS = {
        "name": 10,
        "category": 8,
        "spice_level": 8,
        "dietary": 8,
        "id": 20,           # explicit ID like "M01"
        "taste_profile": 3,
        "description": 2,
        "how_its_made": 1,
    }

    @staticmethod
    def _score_item(item: MenuItem, tokens: list[str]) -> int:
        """Weighted keyword score. Negated tokens ('not spicy') are skipped."""
        # Strip negated tokens ("not X" / "no X") so Butter Chicken's
        # "Not spicy at all" doesn't register as a hit for "spicy".
        tokens = [t.lower() for t in tokens]
        effective: list[str] = []
        skip_next = False
        for i, tok in enumerate(tokens):
            if skip_next:
                skip_next = False
                continue
            if tok in ("not", "no") and i + 1 < len(tokens):
                skip_next = True  # drop the next token
                continue
            effective.append(tok)
        if not effective:
            return 0

        def field_hit(value: str | None, token: str) -> bool:
            if not value:
                return False
            hay = value.lower()
            if token not in hay:
                return False
            # Also reject if the token appears only as part of a "not X" /
            # "no X" phrase inside the field itself (prose like "Not spicy
            # at all" inside a description). Cheap check: is 'not <token>'
            # or 'no <token>' in the haystack AND plain <token> only
            # appears adjacent to those negations? Simple heuristic: if
            # the string "not <token>" appears, we count the field as a
            # miss unless there's another unnegated occurrence.
            negated = hay.count(f"not {token}") + hay.count(f"no {token}")
            total = hay.count(token)
            return (total - negated) > 0

        score = 0
        dietary_joined = " ".join(item.dietary or [])
        for tok in effective:
            if tok.upper() == item.id:
                score += MenuRepo._FIELD_WEIGHTS["id"]
            if field_hit(item.name, tok):
                score += MenuRepo._FIELD_WEIGHTS["name"]
            if field_hit(item.category, tok):
                score += MenuRepo._FIELD_WEIGHTS["category"]
            if field_hit(item.spice_level, tok):
                score += MenuRepo._FIELD_WEIGHTS["spice_level"]
            if field_hit(dietary_joined, tok):
                score += MenuRepo._FIELD_WEIGHTS["dietary"]
            if field_hit(item.taste_profile, tok):
                score += MenuRepo._FIELD_WEIGHTS["taste_profile"]
            if field_hit(item.description, tok):
                score += MenuRepo._FIELD_WEIGHTS["description"]
            if field_hit(item.how_its_made, tok):
                score += MenuRepo._FIELD_WEIGHTS["how_its_made"]
        return score

    # Spice synonyms so "spicy" matches items tagged "hot" / "medium-hot".
    # "mild" deliberately does NOT expand to "none" — unseasoned drinks
    # aren't what the user means by "mild dish".
    _SPICE_SYNONYMS = {
        "spicy": ["spicy", "hot"],
        "hot": ["hot", "spicy"],
    }

    def search_keywords(
        self, query: str, include_unavailable: bool = False
    ) -> list[MenuItem]:
        """Tokenize the query and return items ranked by weighted hits across
        structured fields (name / category / spice_level / dietary) and prose
        fields (taste_profile / description / how_its_made).

        - Hits in structured fields outweigh prose hits.
        - "Not spicy" / "no X" in the query (or in a description) don't
          contribute to the score.
        - Spice words ("spicy", "hot", "mild") match the corresponding
          spice_level values.
        """
        tokens = [t for t in (query or "").strip().split() if t]
        if not tokens:
            return []

        # Expand spice synonyms so the SQL pre-filter actually includes dishes
        # where spice_level is "medium-hot" etc. when the user says "spicy".
        expanded: list[str] = []
        for t in tokens:
            expanded.extend(self._SPICE_SYNONYMS.get(t.lower(), [t]))

        q = self.db.query(MenuItem)
        if not include_unavailable:
            q = q.filter(MenuItem.available == True)  # noqa: E712
        q = q.filter(or_(*_token_conditions(expanded)))
        items = q.all()

        scored = [(self._score_item(i, expanded), i) for i in items]
        # Drop items whose total score is zero (all hits were negated).
        scored = [(s, i) for s, i in scored if s > 0]
        scored.sort(key=lambda si: (-si[0], si[1].category, si[1].id))
        return [i for _, i in scored]

    def semantic_search(
        self,
        query_vec: list[float],
        limit: int = 10,
        include_unavailable: bool = False,
    ) -> list[MenuItem]:
        """Nearest dishes to a query embedding by cosine distance.

        Rows without an embedding are skipped. Requires the pgvector column to
        exist and be populated.
        """
        q = self.db.query(MenuItem).filter(MenuItem.embedding.isnot(None))
        if not include_unavailable:
            q = q.filter(MenuItem.available == True)  # noqa: E712
        q = q.order_by(MenuItem.embedding.cosine_distance(query_vec)).limit(limit)
        return q.all()

    def hybrid_search(
        self, query: str, limit: int = 10, include_unavailable: bool = False
    ) -> list[MenuItem]:
        """Blend keyword ranking with semantic similarity (reciprocal rank
        fusion). Falls back to keyword-only when embeddings are unavailable."""
        from services.embeddings import embed_text  # local import avoids cycle

        keyword_hits = self.search_keywords(query, include_unavailable=include_unavailable)

        semantic_hits: list[MenuItem] = []
        query_vec = embed_text(query)
        if query_vec is not None:
            try:
                semantic_hits = self.semantic_search(
                    query_vec, limit=limit, include_unavailable=include_unavailable
                )
            except Exception:
                semantic_hits = []

        if not semantic_hits:
            return keyword_hits[:limit] if limit else keyword_hits

        # Reciprocal rank fusion (k=60 is the conventional constant).
        K = 60
        scores: dict[str, float] = {}
        by_id: dict[str, MenuItem] = {}
        for rank, item in enumerate(keyword_hits):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (K + rank)
            by_id[item.id] = item
        for rank, item in enumerate(semantic_hits):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (K + rank)
            by_id[item.id] = item

        ordered = sorted(by_id.values(), key=lambda i: -scores[i.id])
        return ordered[:limit] if limit else ordered

    def filter_items(
        self,
        *,
        category: str | None = None,
        dietary: list[str] | None = None,
        spice_level: str | None = None,
        max_price: float | None = None,
        keyword: str | None = None,
        include_unavailable: bool = False,
    ) -> list[MenuItem]:
        """Composable filter. All provided criteria must match (AND)."""
        q = self.db.query(MenuItem)
        if not include_unavailable:
            q = q.filter(MenuItem.available == True)  # noqa: E712

        if category:
            q = q.filter(MenuItem.category.ilike(f"%{category.strip()}%"))
        if spice_level:
            q = q.filter(MenuItem.spice_level.ilike(f"%{spice_level.strip()}%"))
        if max_price is not None:
            q = q.filter(MenuItem.price <= cast(max_price, Numeric))
        if dietary:
            # Every requested tag must appear as an exact element in the
            # dietary JSONB array. JSONB containment avoids the substring
            # false positives (e.g. "vegetarian" matching "non-vegetarian").
            for tag in dietary:
                q = q.filter(
                    MenuItem.dietary.op("@>")(cast([tag.strip()], JSONB))
                )
        if keyword:
            tokens = [t for t in keyword.strip().split() if t]
            if tokens:
                q = q.filter(or_(*_token_conditions(tokens)))

        return q.order_by(MenuItem.category, MenuItem.id).all()

    def create(self, **kwargs) -> MenuItem:
        item = MenuItem(**kwargs)
        self.db.add(item)
        self.db.flush()
        return item

    def update(self, item_id: str, **kwargs) -> MenuItem | None:
        item = self.get_by_id(item_id)
        if not item:
            return None
        for key, value in kwargs.items():
            setattr(item, key, value)
        self.db.flush()
        return item

    def count(self) -> int:
        return self.db.query(MenuItem).count()
