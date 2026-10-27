# SRU Global database foundation

`schema.sql` is the readable PostgreSQL schema.
`api/migrations/versions/001_initial_schema.py` is the first Alembic migration.

Do not paste this into the Supabase dashboard manually.
The next step is to connect Alembic to your Supabase PostgreSQL database and run:

    alembic upgrade head

That will create the tables.
