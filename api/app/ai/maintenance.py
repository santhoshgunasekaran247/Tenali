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
        drafts = db.execute(text("""select count(*) from ai_action_drafts d join ai_conversations c
            on c.id=d.conversation_id and c.company_id=d.company_id and c.user_id=d.user_id
            where d.status<>'discarded' and (d.expires_at<=now() or c.expires_at<=now() or c.status='deleted')""")).scalar_one()
        print(f"Expired/deleted private drafts to scrub: {drafts}")
        reports = db.execute(text("""select count(*) from ai_report_files r join ai_executions e on e.id=r.id
            join ai_conversations c on c.id=e.conversation_id and c.company_id=r.company_id and c.user_id=r.user_id
            where r.content is not null and (r.expires_at<=now() or c.expires_at<=now() or c.status='deleted')""")).scalar_one()
        print(f"Expired/deleted private reports to scrub: {reports}")
        if not args.apply:
            return
        db.execute(text("""update ai_messages m set content='' from ai_conversations c
            where m.conversation_id=c.id and m.company_id=c.company_id and m.user_id=c.user_id
            and c.expires_at<=now()"""))
        db.execute(text("""update ai_conversations set title='Expired conversation',status='deleted',version=version+1
            where expires_at<=now() and status<>'deleted'"""))
        db.execute(text("delete from ai_user_context where expires_at<=now()"))
        db.execute(text("""update ai_action_drafts d set payload='{}',validation=null,status='discarded',
            approved_at=null,approved_version=null,version=version+1 from ai_conversations c
            where c.id=d.conversation_id and c.company_id=d.company_id and c.user_id=d.user_id
            and d.status<>'discarded' and (d.expires_at<=now() or c.expires_at<=now() or c.status='deleted')"""))
        db.execute(text("""update ai_attachments a set content=null,extracted_text=null,file_name='Removed'
            from ai_conversations c where c.id=a.conversation_id and c.company_id=a.company_id and c.user_id=a.user_id
            and (a.expires_at<=now() or c.expires_at<=now() or c.status='deleted')"""))
        db.execute(text("""update ai_voice_requests v set transcript=null from ai_conversations c
            where c.id=v.conversation_id and c.company_id=v.company_id and c.user_id=v.user_id
            and (v.expires_at<=now() or c.expires_at<=now() or c.status='deleted')"""))
        db.execute(text("""update ai_report_files r set content=null from ai_executions e,ai_conversations c
            where r.id=e.id and c.id=e.conversation_id and c.company_id=r.company_id and c.user_id=r.user_id
            and (r.expires_at<=now() or c.expires_at<=now() or c.status='deleted')"""))
        db.commit()
        print("Expired content scrubbed. Usage and audit metadata retained.")


if __name__ == "__main__":
    main()
