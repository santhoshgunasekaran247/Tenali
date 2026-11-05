"""Assign permanent two-character store identifiers for compact invoice numbers."""
from alembic import op

revision = "035_invoice_store_codes"
down_revision = "034_public_policies"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table stores add column invoice_code text;
        do $$ begin
            if exists (select 1 from stores group by company_id having count(*) > 1295) then
                raise exception 'Two-character invoice identifiers support at most 1295 stores per workspace';
            end if;
        end $$;
        with numbered as (
            select id, row_number() over (partition by company_id order by is_default desc, created_at, id)::integer as n
            from stores
        )
        update stores set invoice_code =
            substr('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', numbered.n / 36 + 1, 1) ||
            substr('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', numbered.n % 36 + 1, 1)
        from numbered where stores.id = numbered.id;
        alter table stores alter column invoice_code set not null;
        alter table stores add constraint stores_invoice_code_format check (invoice_code ~ '^[0-9A-Z]{2}$');
        alter table stores add constraint stores_company_invoice_code_key unique(company_id, invoice_code);

        create function assign_store_invoice_code() returns trigger language plpgsql as $$
        declare
            allocated text;
        begin
            if TG_OP = 'UPDATE' then
                if new.invoice_code is distinct from old.invoice_code then
                    raise exception 'Store invoice identifiers cannot be changed';
                end if;
                return new;
            end if;
            perform 1 from companies where id = new.company_id for update;
            select candidate.code into allocated from (
                select n, substr('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', n / 36 + 1, 1) ||
                    substr('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ', n % 36 + 1, 1) as code
                from generate_series(1, 1295) n
            ) candidate
            where not exists (select 1 from stores where company_id = new.company_id and invoice_code = candidate.code)
            order by candidate.n limit 1;
            if allocated is null then
                raise exception 'This workspace has reached the limit of 1295 store invoice identifiers'
                    using errcode = '23514';
            end if;
            new.invoice_code := allocated;
            return new;
        end $$;
        create trigger stores_invoice_code before insert or update of invoice_code on stores
            for each row execute function assign_store_invoice_code();
    """)


def downgrade():
    raise NotImplementedError("Store invoice identifiers must remain permanent")
