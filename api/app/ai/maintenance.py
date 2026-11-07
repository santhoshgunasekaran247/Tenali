"""Scrub expired private chat content; usage and audit metadata remain."""
import argparse

from sqlalchemy import text

from app.core.database import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Scrub content instead of a read-only count")
    args = parser.parse_args()
    with SessionLocal() as db:
        count = db.execute(text("""select count(*) from ai_conversations
            where expires_at<=now() and status<>'deleted'""")).scalar_one()
        print(f"Expired conversations to scrub: {count}")
        if not args.apply:
            return
        db.execute(text("""update ai_messages m set content='' from ai_conversations c
            where m.conversation_id=c.id and m.company_id=c.company_id and m.user_id=c.user_id
            and c.expires_at<=now()"""))
        db.execute(text("""update ai_conversations set title='Expired conversation',status='deleted',version=version+1
            where expires_at<=now() and status<>'deleted'"""))
        db.execute(text("delete from ai_user_context where expires_at<=now()"))
        db.commit()
        print("Expired content scrubbed. Usage and audit metadata retained.")


if __name__ == "__main__":
    main()
