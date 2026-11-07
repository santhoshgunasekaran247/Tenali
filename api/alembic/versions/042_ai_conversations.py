"""Private assistant conversations, usage reservations, and audit metadata."""
from alembic import op

revision = "042_ai_conversations"
down_revision = "041_ai_feature_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table ai_conversations (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            title text not null check(length(title) between 1 and 120),
            status text not null default 'active' check(status in ('active','archived','deleted')),
            version integer not null default 1,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            expires_at timestamptz not null,
            unique(company_id,user_id,id),
            foreign key(company_id,user_id) references tenant_users(company_id,id)
        );
        create index ai_conversation_history on ai_conversations(company_id,user_id,updated_at desc,id);
        create table ai_messages (
            id uuid primary key default gen_random_uuid(),
            sequence bigint generated always as identity,
            company_id uuid not null,
            user_id uuid not null,
            conversation_id uuid not null,
            client_key uuid not null,
            role text not null check(role in ('user','assistant')),
            content text not null check(length(content)<=12000),
            status text not null check(status in ('pending','completed','failed','unknown')),
            error_code text,
            deadline timestamptz,
            created_at timestamptz not null default now(),
            unique(company_id,user_id,conversation_id,client_key,role),
            unique(company_id,user_id,id),
            foreign key(company_id,user_id,conversation_id) references ai_conversations(company_id,user_id,id)
        );
        create index ai_message_history on ai_messages(company_id,user_id,conversation_id,sequence);
        create table ai_user_context (
            company_id uuid not null,
            user_id uuid not null,
            preference text not null check(preference in ('language','instructions')),
            value text not null check(length(value)<=500),
            updated_at timestamptz not null default now(),
            expires_at timestamptz not null,
            primary key(company_id,user_id,preference),
            foreign key(company_id,user_id) references tenant_users(company_id,id)
        );
        create table ai_usage_reservations (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            message_id uuid not null,
            model text not null,
            pricing_version integer not null,
            input_rate numeric(14,6) not null check(input_rate>0),
            output_rate numeric(14,6) not null check(output_rate>0),
            reserved_tokens bigint not null check(reserved_tokens>0),
            reserved_cost numeric(16,8) not null check(reserved_cost>0),
            charged_tokens bigint not null check(charged_tokens>=0),
            charged_cost numeric(16,8) not null check(charged_cost>=0),
            status text not null default 'pending' check(status in ('pending','settled','unknown')),
            created_at timestamptz not null default now(),
            unique(company_id,user_id,message_id),
            unique(company_id,user_id,id),
            foreign key(company_id,user_id,message_id) references ai_messages(company_id,user_id,id)
        );
        create index ai_usage_budget on ai_usage_reservations(company_id,created_at);
        create table ai_usage_logs (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            reservation_id uuid not null unique,
            model text not null,
            provider_reference text,
            status text not null check(status in ('completed','failed','unknown')),
            input_tokens bigint,
            cached_input_tokens bigint,
            output_tokens bigint,
            estimated_cost numeric(16,8) not null,
            error_code text,
            created_at timestamptz not null default now(),
            foreign key(company_id,user_id) references tenant_users(company_id,id),
            foreign key(company_id,user_id,reservation_id) references ai_usage_reservations(company_id,user_id,id)
        );
        create table ai_audit_events (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,
            user_id uuid not null,
            conversation_id uuid,
            event_type text not null,
            correlation_id uuid not null,
            created_at timestamptz not null default now(),
            foreign key(company_id,user_id) references tenant_users(company_id,id),
            foreign key(company_id,user_id,conversation_id) references ai_conversations(company_id,user_id,id)
        );
        create index ai_audit_history on ai_audit_events(company_id,user_id,created_at);
        do $$ declare item text; begin
            foreach item in array array['ai_conversations','ai_messages','ai_user_context',
                                        'ai_usage_reservations','ai_usage_logs','ai_audit_events'] loop
                execute format('alter table %I enable row level security',item);
                execute format('create policy ai_private_scope on %I to tenali_runtime
                    using(company_id=tenali_current_company() and user_id=nullif(current_setting(''app.actor_user_id'',true),'''')::uuid)
                    with check(company_id=tenali_current_company() and user_id=nullif(current_setting(''app.actor_user_id'',true),'''')::uuid)',item);
                execute format('grant select on %I to tenali_runtime',item);
            end loop;
        end $$;
        grant insert,update on ai_conversations,ai_messages,ai_user_context to tenali_runtime;
        grant usage on sequence ai_messages_sequence_seq to tenali_runtime;
        grant delete on ai_user_context to tenali_runtime;
        grant insert on ai_usage_logs,ai_audit_events to tenali_runtime;
        grant update(status,charged_tokens,charged_cost) on ai_usage_reservations to tenali_runtime;

        create function tenali_ai_member_active() returns boolean language sql stable
            security definer set search_path=public,pg_temp as $$
            select exists(select 1 from tenant_memberships m
                join tenant_users u on u.id=m.user_id and u.company_id=m.company_id and u.is_active
                where m.company_id=tenali_current_company() and m.is_active and m.role<>'viewer'
                and m.user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
        $$;
        revoke all on function tenali_ai_member_active() from public;
        grant execute on function tenali_ai_member_active() to tenali_runtime;

        create function tenali_ai_reserve(message uuid, model_name text, input_bound integer, output_bound integer)
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
        revoke all on function tenali_ai_reserve(uuid,text,integer,integer) from public;
        grant execute on function tenali_ai_reserve(uuid,text,integer,integer) to tenali_runtime;
        create function tenali_ai_usage_totals() returns table(requests bigint,tokens numeric,cost numeric)
            language sql stable security definer set search_path=public,pg_temp as $$
            select count(*),coalesce(sum(charged_tokens),0),coalesce(sum(charged_cost),0)
            from ai_usage_reservations where company_id=tenali_current_company() and tenali_feature_admin()
                and created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC'
        $$;
        revoke all on function tenali_ai_usage_totals() from public;
        grant execute on function tenali_ai_usage_totals() to tenali_runtime;
    """)


def downgrade():
    op.execute("""
        drop function tenali_ai_usage_totals();
        drop function tenali_ai_member_active();
        drop function tenali_ai_reserve(uuid,text,integer,integer);
        drop table ai_audit_events,ai_usage_logs,ai_usage_reservations,ai_user_context,ai_messages,ai_conversations;
    """)
