"""Customer repository."""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.models.customer import Customer


class CustomerRepo:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, customer_id: str) -> Customer | None:
        return self.db.get(Customer, customer_id)

    def get_by_code(self, code: str) -> Customer | None:
        return (
            self.db.query(Customer)
            .filter(Customer.code == code.strip())
            .first()
        )

    def get_by_phone(self, phone: str) -> Customer | None:
        return (
            self.db.query(Customer)
            .filter(Customer.phone == phone.strip())
            .first()
        )

    def code_exists(self, code: str) -> bool:
        return (
            self.db.query(Customer).filter(Customer.code == code).count() > 0
        )

    def search(self, query: str | None = None, limit: int = 100) -> list[Customer]:
        q = self.db.query(Customer)
        if query:
            like = f"%{query.strip()}%"
            q = q.filter(
                or_(
                    Customer.code.ilike(like),
                    Customer.phone.ilike(like),
                    Customer.name.ilike(like),
                    Customer.area.ilike(like),
                )
            )
        return q.order_by(Customer.last_order_at.desc().nullslast(), Customer.created_at.desc()).limit(limit).all()

    def create(self, **kwargs) -> Customer:
        customer = Customer(**kwargs)
        self.db.add(customer)
        self.db.flush()
        return customer

    def update(self, customer_id: str, **kwargs) -> Customer | None:
        customer = self.get_by_id(customer_id)
        if not customer:
            return None
        for key, value in kwargs.items():
            setattr(customer, key, value)
        self.db.flush()
        return customer
