"""Per-connection call state for the public parcel voice line.

The voice line is anonymous: a caller is only tied to a customer record once
the agent identifies them mid-conversation (via lookup_customer or
register_customer). The tool wrappers share one mutable CallSession so that,
after identification, the cart/order tools know whose order they're building.
"""

from dataclasses import dataclass


@dataclass
class CallSession:
    # Set once the agent has identified or registered the caller.
    customer_id: str | None = None
    customer_code: str | None = None
    customer_name: str | None = None

    def identify(self, customer) -> None:
        self.customer_id = customer.id
        self.customer_code = customer.code
        self.customer_name = customer.name

    @property
    def is_identified(self) -> bool:
        return self.customer_id is not None
