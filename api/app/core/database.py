from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from fastapi import HTTPException, Request

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


@event.listens_for(Session, "after_begin")
def apply_tenant_scope(session, transaction, connection):
    context = session.info.get("tenant_context")
    if context:
        connection.exec_driver_sql("SET LOCAL ROLE tenali_runtime")
        connection.execute(text("select set_config('app.tenant_id',:company,true),set_config('app.actor_user_id',:actor,true)"),
                           {"company": str(context["company_id"]), "actor": str(context.get("user_id") or "")})


def get_db(request: Request):
    context = getattr(request.state, "tenant", None)
    if not context:
        raise HTTPException(401, "Workspace access is required")
    db = SessionLocal()
    db.info["tenant_context"] = context
    try:
        yield db
    finally:
        db.close()
