"""Customer service: lookup, registration (with code allocation), updates."""

import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.restaurant.codes import generate_unique_code
from db.models.customer import Customer
from db.repositories.customer_repo import CustomerRepo


def _words(text: str | None) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def _name_matches(on_file: str | None, said: str | None) -> bool:
    """Every word the caller said is part of the name on file ("Priya" matches
    "Priya Sharma")."""
    said_words, file_words = set(_words(said)), set(_words(on_file))
    return bool(said_words) and said_words <= file_words


def _place_matches(customer: Customer, said: str | None) -> bool:
    """The pincode on file, or the area when the record has no pincode."""
    if customer.pincode:
        return re.sub(r"\D", "", said or "") == re.sub(r"\D", "", customer.pincode)
    said_words = _words(said)
    return bool(said_words) and said_words == _words(customer.area)


def normalize_phone(raw: str | None) -> str | None:
    """Reduce a spoken/typed phone to comparable digits.

    Strips spaces, punctuation, a leading +91 / 91 / 0 (India) so "+91 98200
    12345", "098200 12345" and "9820012345" all match. Returns None for blanks.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits


# Fields a caller can set/amend on their record.
EDITABLE_FIELDS = {
    "name",
    "address_line",
    "area",
    "pincode",
    "landmark",
    "preferences",
    "allergies",
    "notes",
}


class CustomerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CustomerRepo(db)

    def get_by_id(self, customer_id: str) -> Customer:
        customer = self.repo.get_by_id(customer_id)
        if not customer:
            raise ValueError(f"Customer '{customer_id}' not found")
        return customer

    def verify(self, code_or_phone: str, *, name: str, place: str) -> Customer | None:
        """A returning customer, only if the caller also knows the name and the
        delivery pincode (or, when none is on file, the area) on the record.
        A code or phone number alone is guessable, so it never identifies."""
        cust = self.lookup(code_or_phone)
        if cust and _name_matches(cust.name, name) and _place_matches(cust, place):
            return cust
        return None

    def lookup(self, code_or_phone: str) -> Customer | None:
        """Resolve a returning customer by their 4-digit code or phone number."""
        if not code_or_phone:
            return None
        token = code_or_phone.strip()

        # A bare 4-digit token is almost certainly a code.
        digits_only = re.sub(r"\D", "", token)
        if len(digits_only) == 4:
            found = self.repo.get_by_code(digits_only)
            if found:
                return found

        # Otherwise try phone (normalized), then fall back to code.
        phone = normalize_phone(token)
        if phone:
            found = self.repo.get_by_phone(phone)
            if found:
                return found
        return self.repo.get_by_code(token)

    def create_customer(
        self,
        *,
        name: str | None = None,
        phone: str | None = None,
        address_line: str | None = None,
        area: str | None = None,
        pincode: str | None = None,
        landmark: str | None = None,
        preferences: str | None = None,
        allergies: str | None = None,
        notes: str | None = None,
    ) -> Customer:
        """Create a customer with a freshly allocated unique 4-digit code.

        If the phone already belongs to a customer, returns that existing
        record instead of creating a duplicate.
        """
        norm_phone = normalize_phone(phone)
        if norm_phone:
            existing = self.repo.get_by_phone(norm_phone)
            if existing:
                return existing

        code = generate_unique_code(self.repo.code_exists)
        try:
            return self.repo.create(
                code=code,
                phone=norm_phone,
                name=name,
                address_line=address_line,
                area=area,
                pincode=pincode,
                landmark=landmark,
                preferences=preferences,
                allergies=allergies,
                notes=notes,
            )
        except IntegrityError:
            # Lost a check-then-insert race on the unique phone (or code) — undo
            # the failed insert and return the row that won.
            self.db.rollback()
            if norm_phone:
                won = self.repo.get_by_phone(norm_phone)
                if won:
                    return won
            raise

    def update_customer(self, customer_id: str, **fields) -> Customer:
        clean = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS and v is not None}
        if "phone" in fields and fields["phone"] is not None:
            clean["phone"] = normalize_phone(fields["phone"])
        customer = self.repo.update(customer_id, **clean)
        if not customer:
            raise ValueError(f"Customer '{customer_id}' not found")
        return customer

    def search(self, query: str | None = None, limit: int = 100) -> list[Customer]:
        return self.repo.search(query=query, limit=limit)

    def search_page(
        self, query: str | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[list[Customer], int]:
        return self.repo.search_page(query=query, limit=limit, offset=offset)
