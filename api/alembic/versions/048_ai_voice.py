"""Private duration-metered voice transcription and stable request recovery."""
from alembic import op

revision = "048_ai_voice"
down_revision = "047_ai_private_media"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        create table ai_voice_requests (
            id uuid primary key default gen_random_uuid(),
            company_id uuid not null,user_id uuid not null,conversation_id uuid not null,
            client_key uuid not null,audio_hash text not null,language text not null check(language in ('auto','en','ta')),
            audio_seconds numeric(10,6) not null check(audio_seconds between 0.5 and 60),
            transcript text check(length(transcript)<=4000),
            status text not null default 'pending' check(status in ('pending','completed','failed','unknown')),
            error_code text,created_at timestamptz not null default now(),deadline timestamptz not null,
            expires_at timestamptz not null,
            unique(company_id,user_id,conversation_id,client_key),
            unique(company_id,user_id,id),
            foreign key(company_id,user_id,conversation_id) references ai_conversations(company_id,user_id,id)
        );
        create index ai_voice_expiry on ai_voice_requests(expires_at) where transcript is not null;
        alter table ai_voice_requests enable row level security;
        create policy ai_voice_private on ai_voice_requests to tenali_runtime
            using(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid)
            with check(company_id=tenali_current_company() and user_id=nullif(current_setting('app.actor_user_id',true),'')::uuid);
        grant select,insert,update on ai_voice_requests to tenali_runtime;
        alter table ai_usage_reservations alter column message_id drop not null;
        alter table ai_usage_reservations alter column input_rate drop not null;
        alter table ai_usage_reservations alter column output_rate drop not null;
        alter table ai_usage_reservations drop constraint ai_usage_reservations_reserved_tokens_check;
        alter table ai_usage_reservations add constraint ai_usage_reservations_reserved_tokens_check check(reserved_tokens>=0);
        alter table ai_usage_reservations add column voice_id uuid;
        alter table ai_usage_reservations add column audio_seconds numeric(10,6);
        alter table ai_usage_reservations add column audio_rate numeric(14,6);
        alter table ai_usage_reservations add constraint ai_usage_voice_owner
            foreign key(company_id,user_id,voice_id) references ai_voice_requests(company_id,user_id,id);
        alter table ai_usage_reservations add unique(company_id,user_id,voice_id);
        alter table ai_usage_reservations add constraint ai_usage_kind check(
            (message_id is not null and voice_id is null and input_rate>0 and output_rate>0
                and input_rate is not null and output_rate is not null and reserved_tokens>0
                and audio_seconds is null and audio_rate is null)
            or (message_id is null and voice_id is not null and input_rate is null and output_rate is null
                and reserved_tokens=0 and audio_seconds between 1 and 60 and audio_rate>0
                and audio_seconds is not null and audio_rate is not null));
        create function tenali_ai_reserve_voice(voice uuid, model_name text) returns uuid
            language plpgsql security definer set search_path=public,pg_temp as $$
        declare company uuid:=tenali_current_company();
            actor uuid:=nullif(current_setting('app.actor_user_id',true),'')::uuid;
            config jsonb; overrides jsonb; config_version integer;
            seconds numeric; rate numeric; cost numeric; daily bigint; spend numeric; result uuid;
        begin
            perform pg_advisory_xact_lock(hashtextextended('ai-budget:'||company::text,0));
            select ceil(v.audio_seconds) into seconds from ai_voice_requests v join ai_conversations c
                on c.id=v.conversation_id and c.company_id=v.company_id and c.user_id=v.user_id
                where v.id=voice and v.company_id=company and v.user_id=actor and v.status='pending'
                and v.expires_at>now() and c.status='active' and c.expires_at>now();
            if not found then raise exception 'Voice ownership rejected' using errcode='42501'; end if;
            if not tenali_ai_member_active()
                or not exists(select 1 from companies where id=company and is_active)
                or not exists(select 1 from tenant_feature_controls where company_id=company and feature_key='ai' and platform_allowed)
                or not exists(select 1 from ai_tenant_settings where company_id=company and tenant_enabled) then
                raise exception 'AI access disabled' using errcode='42501';
            end if;
            select s.config,s.version into config,config_version from ai_platform_settings s where id=true;
            select l.config into overrides from ai_tenant_limits l where l.company_id=company;
            rate:=(config->>'transcription_cost_per_minute')::numeric;
            if not coalesce((config->>'global_enabled')::boolean,false)
                or not coalesce((config->>'voice_inputs_enabled')::boolean,false)
                or model_name is distinct from 'gpt-transcribe'
                or model_name is distinct from config->>'transcription_model' or rate is null or rate<=0 then
                raise exception 'Voice configuration unavailable' using errcode='42501';
            end if;
            cost:=ceil(seconds*rate/60*100000000)/100000000;
            select count(*) filter(where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC'),
                coalesce(sum(charged_cost),0) into daily,spend from ai_usage_reservations where company_id=company
                and created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC';
            if daily>=coalesce((overrides->>'daily_request_limit')::bigint,(config->>'daily_request_limit')::bigint,50)
                or spend+cost>coalesce((overrides->>'monthly_cost_limit')::numeric,(config->>'monthly_cost_limit')::numeric,10) then
                raise exception 'AI usage limit reached' using errcode='P0001';
            end if;
            insert into ai_usage_reservations(company_id,user_id,voice_id,model,pricing_version,audio_seconds,audio_rate,
                reserved_tokens,reserved_cost,charged_tokens,charged_cost)
                values(company,actor,voice,model_name,config_version,seconds,rate,0,cost,0,cost) returning id into result;
            return result;
        end $$;
        revoke all on function tenali_ai_reserve_voice(uuid,text) from public;
        grant execute on function tenali_ai_reserve_voice(uuid,text) to tenali_runtime;
    """)


def downgrade():
    op.execute("""
        do $$ begin
            if exists(select 1 from ai_usage_reservations where voice_id is not null) then
                raise exception 'Cannot downgrade voice after usage has been recorded; retain the metering ledger';
            end if;
        end $$;
        drop function tenali_ai_reserve_voice(uuid,text);
        alter table ai_usage_reservations drop constraint ai_usage_kind;
        alter table ai_usage_reservations drop column voice_id;
        alter table ai_usage_reservations drop column audio_seconds;
        alter table ai_usage_reservations drop column audio_rate;
        alter table ai_usage_reservations alter column message_id set not null;
        alter table ai_usage_reservations alter column input_rate set not null;
        alter table ai_usage_reservations alter column output_rate set not null;
        alter table ai_usage_reservations drop constraint ai_usage_reservations_reserved_tokens_check;
        alter table ai_usage_reservations add constraint ai_usage_reservations_reserved_tokens_check check(reserved_tokens>0);
        drop table ai_voice_requests;
        update ai_platform_settings set config=config-'voice_inputs_enabled'-'transcription_model'-'transcription_cost_per_minute';
    """)
