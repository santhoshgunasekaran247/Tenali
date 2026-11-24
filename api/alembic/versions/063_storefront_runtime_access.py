"""Grant tenant runtime access to storefront builder tables."""

from alembic import op

revision = "063_storefront_runtime_access"
down_revision = "062_storefront_builder"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        do $$ declare table_name text;
        begin
            foreach table_name in array array[
                'product_tags', 'product_tag_products',
                'storefront_sections', 'storefront_section_products',
                'storefront_section_categories', 'storefront_section_brands'
            ] loop
                execute format('alter table %I enable row level security', table_name);
                execute format('drop policy if exists tenali_company_scope on %I', table_name);
                execute format(
                    'create policy tenali_company_scope on %I to tenali_runtime using (company_id = tenali_current_company()) with check (company_id = tenali_current_company())',
                    table_name
                );
                execute format('grant select, insert, update, delete on %I to tenali_runtime', table_name);
            end loop;

            foreach table_name in array array['product_tags', 'storefront_sections'] loop
                execute format('drop trigger if exists tenali_company_relationship on %I', table_name);
                execute format(
                    'create trigger tenali_company_relationship before insert or update on %I for each row execute function tenali_guard_relationships()',
                    table_name
                );
                execute format('drop trigger if exists tenali_audit_change on %I', table_name);
                execute format(
                    'create trigger tenali_audit_change after insert or update or delete on %I for each row execute function tenali_operational_audit()',
                    table_name
                );
            end loop;
        end $$
    """)


def downgrade():
    op.execute("""
        do $$ declare table_name text;
        begin
            foreach table_name in array array[
                'product_tags', 'product_tag_products',
                'storefront_sections', 'storefront_section_products',
                'storefront_section_categories', 'storefront_section_brands'
            ] loop
                execute format('drop policy if exists tenali_company_scope on %I', table_name);
                execute format('alter table %I disable row level security', table_name);
                execute format('revoke select, insert, update, delete on %I from tenali_runtime', table_name);
            end loop;
            foreach table_name in array array['product_tags', 'storefront_sections'] loop
                execute format('drop trigger if exists tenali_company_relationship on %I', table_name);
                execute format('drop trigger if exists tenali_audit_change on %I', table_name);
            end loop;
        end $$
    """)
