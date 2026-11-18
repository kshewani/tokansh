from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.properties.models import ApplicationOperation, Property


class PropertyRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, property_id: str) -> Property | None:
        return self.session.get(Property, property_id)

    def page(self, page: int, page_size: int) -> tuple[list[Property], int]:
        total = self.session.scalar(select(func.count()).select_from(Property))
        rows = self.session.scalars(select(Property).order_by(Property.created_at, Property.id)
                                    .offset((page - 1) * page_size).limit(page_size)).all()
        return list(rows), total or 0

    def operation(self, actor_id: str, key: str) -> ApplicationOperation | None:
        return self.session.scalar(select(ApplicationOperation).where(
            ApplicationOperation.actor_id == actor_id, ApplicationOperation.idempotency_key == key))
