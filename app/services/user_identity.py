from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.security import UserAuthContext
from app.models.user import User


def get_or_create_user(session: Session, auth: UserAuthContext) -> User:
    user = session.exec(select(User).where(User.cognito_sub == auth.sub)).first()
    now = datetime.now(timezone.utc)
    if user:
        changed = False
        if auth.email and user.email != auth.email:
            user.email = auth.email
            changed = True
        if auth.display_name and user.display_name != auth.display_name:
            user.display_name = auth.display_name
            changed = True
        if changed:
            user.updated_at = now
            session.add(user)
            session.commit()
            session.refresh(user)
        return user

    user = User(
        cognito_sub=auth.sub,
        email=auth.email or f"{auth.sub}@unknown.local",
        display_name=auth.display_name,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
