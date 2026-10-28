from sqlalchemy import text


def managed_schema(db) -> bool:
    info=getattr(db,"info",{})
    if info.get("tenali_managed_schema"):
        return True
    if not db.execute(text("select to_regclass('alembic_version')")).scalar_one_or_none():
        return False
    versions=db.execute(text("select version_num from alembic_version")).scalars().all()
    ready=any(str(version).split('_',1)[0].isdigit() and int(str(version).split('_',1)[0])>=13 for version in versions)
    if ready:
        info["tenali_managed_schema"]=True
    return ready