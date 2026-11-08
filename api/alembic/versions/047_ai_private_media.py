"""Private bounded text/image inputs using the existing metered message lifecycle."""
from alembic import op

revision = "047_ai_private_media"
down_revision = "046_ai_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table ai_attachments(
            id uuid primary key,company_id uuid not null,user_id uuid not null,conversation_id uuid not null,
            file_name text not null,mime_type text not null check(mime_type in ('text/plain','image/jpeg')),
            content bytea,extracted_text text,input_bound integer not null check(input_bound between 1 and 16000),
            created_at timestamptz not null default now(),expires_at timestamptz not null,
            unique(company_id,user_id,conversation_id,id),
            foreign key(company_id,user_id,conversation_id) references ai_conversations(company_id,user_id,id),
            check(octet_length(content)<=2097152),check(octet_length(extracted_text)<=12000)
        );
        create index ai_attachment_history on ai_attachments(company_id,user_id,conversation_id);
        alter table ai_attachments enable row level security;
        create policy ai_attachment_private on ai_attachments to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert,update on ai_attachments to tenali_runtime;
        alter table ai_messages add column attachment_ids uuid[] not null default '{}';
    """)
    op.execute("""
        create or replace function tenali_ai_reserve(message uuid, model_name text, input_bound integer, output_bound integer)
            returns uuid language plpgsql security definer set search_path=public,pg_temp as $$
        declare company uuid:=tenali_current_company();
            actor uuid:=nullif(current_setting('app.actor_user_id',true),'')::uuid;
            config jsonb; overrides jsonb; config_version integer; rate_in numeric; rate_out numeric;
            cost numeric; tokens bigint; daily bigint; monthly bigint; spend numeric; result uuid;
            media uuid[]; chat uuid; media_bound integer:=0; item uuid;
        begin
            perform pg_advisory_xact_lock(hashtextextended('ai-budget:'||company::text,0));
            select m.attachment_ids,m.conversation_id into media,chat from ai_messages m where m.id=message
                and m.company_id=company and m.user_id=actor and m.role='user' and m.status='pending';
            if not found then raise exception 'AI message ownership rejected' using errcode='42501'; end if;
            if not exists(select 1 from tenant_memberships m join companies c on c.id=m.company_id
                where m.company_id=company and m.user_id=actor and m.is_active and c.is_active and m.role<>'viewer')
                or not exists(select 1 from tenant_feature_controls where company_id=company
                              and feature_key='ai' and platform_allowed)
                or not exists(select 1 from ai_tenant_settings where company_id=company and tenant_enabled) then
                raise exception 'AI access disabled' using errcode='42501';
            end if;
            select s.config,s.version into config,config_version from ai_platform_settings s where id=true;
            select l.config into overrides from ai_tenant_limits l where l.company_id=company;
            if not coalesce((config->>'global_enabled')::boolean,false)
               or output_bound not between 100 and coalesce((config->>'max_output_tokens')::integer,2000) then
                raise exception 'AI configuration unavailable' using errcode='42501';
            end if;
            if cardinality(media)>0 then
                if cardinality(media)>2 or cardinality(media)<>(select count(distinct x) from unnest(media) x)
                    or not coalesce((config->>'document_inputs_enabled')::boolean,false)
                    or model_name is distinct from config->>'document_model' then
                    raise exception 'AI document configuration unavailable' using errcode='42501';
                end if;
                foreach item in array media loop
                    select a.input_bound into tokens from ai_attachments a where a.id=item and a.company_id=company
                        and a.user_id=actor and a.conversation_id=chat and a.content is not null and a.expires_at>now();
                    if not found then raise exception 'AI attachment ownership rejected' using errcode='42501'; end if;
                    media_bound:=media_bound+tokens;
                end loop;
                if input_bound not between media_bound+1 and media_bound+20000 then
                    raise exception 'AI input bound rejected' using errcode='42501';
                end if;
                rate_in:=(config->>'document_input_cost_per_million')::numeric;
                rate_out:=(config->>'document_output_cost_per_million')::numeric;
            else
                if model_name is distinct from config->>'routine_model' or input_bound not between 1 and 20000 then
                    raise exception 'AI configuration unavailable' using errcode='42501';
                end if;
                rate_in:=(config->>'input_cost_per_million')::numeric;
                rate_out:=(config->>'output_cost_per_million')::numeric;
            end if;
            if rate_in is null or rate_out is null or rate_in<=0 or rate_out<=0 then
                raise exception 'AI pricing unavailable' using errcode='42501';
            end if;
            tokens:=input_bound+output_bound;
            cost:=ceil((input_bound*rate_in+output_bound*rate_out)/1000000*100000000)/100000000;
            select count(*) filter(where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC'),
                coalesce(sum(charged_tokens),0),coalesce(sum(charged_cost),0) into daily,monthly,spend
                from ai_usage_reservations where company_id=company
                and created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC';
            if daily>=coalesce((overrides->>'daily_request_limit')::bigint,(config->>'daily_request_limit')::bigint,50)
                or monthly+tokens>coalesce((overrides->>'monthly_token_limit')::bigint,(config->>'monthly_token_limit')::bigint,1000000)
                or spend+cost>coalesce((overrides->>'monthly_cost_limit')::numeric,(config->>'monthly_cost_limit')::numeric,10) then
                raise exception 'AI usage limit reached' using errcode='P0001';
            end if;
            insert into ai_usage_reservations(company_id,user_id,message_id,model,pricing_version,input_rate,output_rate,
                reserved_tokens,reserved_cost,charged_tokens,charged_cost)
                values(company,actor,message,model_name,config_version,rate_in,rate_out,tokens,cost,tokens,cost)
                returning id into result;
            return result;
        end $$;
    """)


def downgrade():
    op.execute("""
        create or replace function tenali_ai_reserve(message uuid, model_name text, input_bound integer, output_bound integer)
            returns uuid language plpgsql security definer set search_path=public,pg_temp as $$
        declare company uuid:=tenali_current_company();
            actor uuid:=nullif(current_setting('app.actor_user_id',true),'')::uuid;
            config jsonb; overrides jsonb; config_version integer; rate_in numeric; rate_out numeric;
            cost numeric; tokens bigint; daily bigint; monthly bigint; spend numeric; result uuid;
        begin
            perform pg_advisory_xact_lock(hashtextextended('ai-budget:'||company::text,0));
            if not exists(select 1 from ai_messages where id=message and company_id=company
                          and user_id=actor and role='user' and status='pending') then
                raise exception 'AI message ownership rejected' using errcode='42501';
            end if;
            if not exists(select 1 from tenant_memberships m join companies c on c.id=m.company_id
                where m.company_id=company and m.user_id=actor and m.is_active and c.is_active and m.role<>'viewer')
                or not exists(select 1 from tenant_feature_controls where company_id=company
                              and feature_key='ai' and platform_allowed)
                or not exists(select 1 from ai_tenant_settings where company_id=company and tenant_enabled) then
                raise exception 'AI access disabled' using errcode='42501';
            end if;
            select s.config,s.version into config,config_version from ai_platform_settings s where id=true;
            select l.config into overrides from ai_tenant_limits l where l.company_id=company;
            if not coalesce((config->>'global_enabled')::boolean,false)
               or model_name is distinct from config->>'routine_model'
               or input_bound not between 1 and 20000
               or output_bound not between 100 and coalesce((config->>'max_output_tokens')::integer,2000) then
                raise exception 'AI configuration unavailable' using errcode='42501';
            end if;
            rate_in:=(config->>'input_cost_per_million')::numeric;
            rate_out:=(config->>'output_cost_per_million')::numeric;
            if rate_in is null or rate_out is null or rate_in<=0 or rate_out<=0 then
                raise exception 'AI pricing unavailable' using errcode='42501';
            end if;
            tokens:=input_bound+output_bound;
            cost:=ceil((input_bound*rate_in+output_bound*rate_out)/1000000*100000000)/100000000;
            select count(*) filter(where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC'),
                coalesce(sum(charged_tokens),0),coalesce(sum(charged_cost),0) into daily,monthly,spend
                from ai_usage_reservations where company_id=company
                and created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC';
            if daily>=coalesce((overrides->>'daily_request_limit')::bigint,(config->>'daily_request_limit')::bigint,50)
                or monthly+tokens>coalesce((overrides->>'monthly_token_limit')::bigint,(config->>'monthly_token_limit')::bigint,1000000)
                or spend+cost>coalesce((overrides->>'monthly_cost_limit')::numeric,(config->>'monthly_cost_limit')::numeric,10) then
                raise exception 'AI usage limit reached' using errcode='P0001';
            end if;
            insert into ai_usage_reservations(company_id,user_id,message_id,model,pricing_version,input_rate,output_rate,
                reserved_tokens,reserved_cost,charged_tokens,charged_cost)
                values(company,actor,message,model_name,config_version,rate_in,rate_out,tokens,cost,tokens,cost)
                returning id into result;
            return result;
        end $$;
    """)
    op.execute("""
        alter table ai_messages drop column attachment_ids;
        drop table ai_attachments;
        update ai_platform_settings set config=config-'document_inputs_enabled'
            -'document_input_cost_per_million'-'document_output_cost_per_million';
    """)
