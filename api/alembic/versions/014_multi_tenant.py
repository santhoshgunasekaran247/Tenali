"""Introduce tenant identity, verified domains and database-enforced segregation."""

from alembic import op

revision = "014_multi_tenant"
down_revision = "013_runtime_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        alter table companies add column if not exists tenant_slug text;
        update companies set tenant_slug='legacy-'||replace(id::text,'-','') where tenant_slug is null;
        create unique index if not exists uq_companies_tenant_slug on companies(tenant_slug);
        create table tenant_users (
            id uuid primary key default gen_random_uuid(),email text not null unique,
            display_name text not null,password_hash text not null,is_active boolean not null default true,
            created_at timestamptz not null default now()
        );
        create table tenant_memberships (
            company_id uuid not null references companies(id),user_id uuid not null references tenant_users(id),
            role text not null check(role in ('owner','admin','staff','viewer')),
            is_active boolean not null default true,created_at timestamptz not null default now(),
            primary key(company_id,user_id)
        );
        create table tenant_sessions (
            token_hash text primary key,user_id uuid not null references tenant_users(id),
            company_id uuid not null references companies(id),expires_at timestamptz not null,
            created_at timestamptz not null default now()
        );
        create index idx_tenant_sessions_expiry on tenant_sessions(expires_at);
        create table tenant_domains (
            id uuid primary key default gen_random_uuid(),company_id uuid not null references companies(id),
            hostname text not null unique,verification_token text not null,verified_at timestamptz,
            created_at timestamptz not null default now()
        );
        create table tenant_auth_attempts (
            bucket text primary key,attempts integer not null default 1,window_start timestamptz not null default now()
        );
        alter table audit_events add column if not exists actor_user_id uuid references tenant_users(id);
        do $$ begin
            if not exists(select 1 from pg_roles where rolname='tenali_runtime') then
                create role tenali_runtime nologin nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
            end if;
            execute format('grant tenali_runtime to %I',current_user);
        end $$;
        grant usage on schema public to tenali_runtime;
        grant select on alembic_version to tenali_runtime;
        create or replace function tenali_current_company() returns uuid language sql stable as $$
            select nullif(current_setting('app.tenant_id',true),'')::uuid
        $$;
        create or replace function tenali_record_company(parent_table text,record_id uuid) returns uuid
        language plpgsql stable as $$
        declare result uuid;
        begin
            if record_id is null then return null; end if;
            if parent_table='companies' then return record_id; end if;
            if parent_table in ('product_variants','product_images','vendor_contributions') then
                execute format('select p.company_id from %I item join products p on p.id=item.product_id where item.id=$1',parent_table) into result using record_id;
            elsif parent_table='invoice_items' then
                select p.company_id into result from invoice_items item join invoices p on p.id=item.invoice_id where item.id=record_id;
            elsif parent_table='purchase_items' then
                select p.company_id into result from purchase_items item join purchases p on p.id=item.purchase_id where item.id=record_id;
            elsif parent_table='document_links' then
                select p.company_id into result from document_links item join documents p on p.id=item.document_id where item.id=record_id;
            else
                execute format('select company_id from %I where id=$1',parent_table) into result using record_id;
            end if;
            return result;
        end $$;
        create or replace function tenali_guard_relationships() returns trigger language plpgsql as $$
        declare payload jsonb; owner_id uuid; parent_id uuid; parent_company uuid; reference record;
        begin
            payload:=to_jsonb(NEW);
            owner_id:=nullif(payload->>'company_id','')::uuid;
            if TG_TABLE_NAME='companies' then owner_id:=(payload->>'id')::uuid; end if;
            if owner_id is null then
                if payload ? 'product_id' then owner_id:=tenali_record_company('products',(payload->>'product_id')::uuid);
                elsif payload ? 'invoice_id' then owner_id:=tenali_record_company('invoices',(payload->>'invoice_id')::uuid);
                elsif payload ? 'purchase_id' then owner_id:=tenali_record_company('purchases',(payload->>'purchase_id')::uuid);
                elsif payload ? 'document_id' then owner_id:=tenali_record_company('documents',(payload->>'document_id')::uuid);
                end if;
            end if;
            for reference in select attribute.attname as child_column,parent.relname as parent_table
                from pg_constraint constraint_row
                join pg_class parent on parent.oid=constraint_row.confrelid
                join pg_attribute attribute on attribute.attrelid=constraint_row.conrelid and attribute.attnum=constraint_row.conkey[1]
                where constraint_row.contype='f' and constraint_row.conrelid=TG_RELID and array_length(constraint_row.conkey,1)=1
                and (parent.relname='companies' or exists(select 1 from pg_attribute column_row where column_row.attrelid=parent.oid and column_row.attname='company_id')
                     or parent.relname in ('product_variants','product_images','vendor_contributions','invoice_items','purchase_items','document_links'))
            loop
                parent_id:=nullif(payload->>reference.child_column,'')::uuid;
                if parent_id is not null then
                    parent_company:=tenali_record_company(reference.parent_table,parent_id);
                    if parent_company is null or parent_company is distinct from owner_id then
                        raise exception 'Cross-company relationship rejected' using errcode='23514';
                    end if;
                end if;
            end loop;
            if payload ? 'variant_id' and payload->>'variant_id' is not null and payload ? 'product_id' then
                if not exists(select 1 from product_variants where id=(payload->>'variant_id')::uuid and product_id=(payload->>'product_id')::uuid) then
                    raise exception 'Variant does not belong to product' using errcode='23514';
                end if;
            end if;
            return NEW;
        end $$;
        do $$ declare item record; table_name text; condition_sql text;
        begin
            for item in select table_row.tablename from pg_tables table_row where table_row.schemaname='public'
                and (table_row.tablename='companies' or exists(select 1 from information_schema.columns column_row where column_row.table_schema='public' and column_row.table_name=table_row.tablename and column_row.column_name='company_id'))
                and table_row.tablename not like 'tenant_%'
            loop
                table_name:=item.tablename;
                condition_sql:=case when table_name='companies' then 'id=tenali_current_company()' else 'company_id=tenali_current_company()' end;
                execute format('alter table %I enable row level security',table_name);
                execute format('create policy tenali_company_scope on %I to tenali_runtime using (%s) with check (%s)',table_name,condition_sql,condition_sql);
                execute format('grant select,insert,update on %I to tenali_runtime',table_name);
                execute format('create trigger tenali_company_relationship before insert or update on %I for each row execute function tenali_guard_relationships()',table_name);
            end loop;
            foreach table_name in array array['product_variants','product_images','vendor_contributions','invoice_items','purchase_items','document_links'] loop
                condition_sql:=case
                    when table_name in ('product_variants','product_images','vendor_contributions') then 'exists(select 1 from products where id=product_id and company_id=tenali_current_company())'
                    when table_name='invoice_items' then 'exists(select 1 from invoices where id=invoice_id and company_id=tenali_current_company())'
                    when table_name='purchase_items' then 'exists(select 1 from purchases where id=purchase_id and company_id=tenali_current_company())'
                    else 'exists(select 1 from documents where id=document_id and company_id=tenali_current_company())' end;
                execute format('alter table %I enable row level security',table_name);
                execute format('create policy tenali_company_scope on %I to tenali_runtime using (%s) with check (%s)',table_name,condition_sql,condition_sql);
                execute format('grant select,insert,update on %I to tenali_runtime',table_name);
                execute format('create trigger tenali_company_relationship before insert or update on %I for each row execute function tenali_guard_relationships()',table_name);
            end loop;
        end $$;
        revoke insert,update on audit_events from tenali_runtime;
    """)
    op.execute("""
        create or replace function tenali_operational_audit() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
        declare old_payload jsonb; new_payload jsonb; record_payload jsonb; owner_id uuid; actor uuid;
        begin
            old_payload:=case when TG_OP='INSERT' then null else to_jsonb(OLD) end;
            new_payload:=case when TG_OP='DELETE' then null else to_jsonb(NEW) end;
            record_payload:=coalesce(new_payload,old_payload);
            owner_id:=nullif(record_payload->>'company_id','')::uuid;
            if TG_TABLE_NAME='companies' then owner_id:=(record_payload->>'id')::uuid; end if;
            if owner_id is null and record_payload ? 'product_id' then select company_id into owner_id from products where id=(record_payload->>'product_id')::uuid; end if;
            actor:=nullif(current_setting('app.actor_user_id',true),'')::uuid;
            old_payload:=old_payload-'file_content'-'document_data'-'line_items'-'logo_url'-'invoice_settings';
            new_payload:=new_payload-'file_content'-'document_data'-'line_items'-'logo_url'-'invoice_settings';
            insert into audit_events(company_id,actor_user_id,action,entity_type,entity_id,old_value,new_value,source_type)
            values(owner_id,actor,TG_OP,TG_TABLE_NAME,(record_payload->>'id')::uuid,old_payload,new_payload,'database');
            return null;
        end $$;
        revoke all on function tenali_operational_audit() from public;
        grant execute on function tenali_operational_audit() to tenali_runtime;
    """)


def downgrade():
    raise NotImplementedError("Tenant identity and isolation cannot be safely downgraded")