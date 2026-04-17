from abc import ABC, abstractmethod

from app.api.v1.schemas.spend import SpendRequest


class PaymentAdapter(ABC):
    @abstractmethod
    async def execute(self, request_id: str, spend_request: SpendRequest) -> dict:
        raise NotImplementedError

