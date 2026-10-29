# Supabase Setup Guide — AO-03

To use Supabase with AO-03, follow these steps:

### 1. Create a Supabase Project
1. Log in to [Supabase](https://supabase.com).
2. Create a new project named `ao03-incident-rca`.
3. Note your **Project URL** and **API Keys** (Anon and Service Role) in Settings -> API.
4. Note your **Database Connection String** in Settings -> Database -> Connection String (URI).

### 2. Apply Migrations
1. In the Supabase dashboard, navigate to the **SQL Editor**.
2. Click **New Query**.
3. Copy the entire contents of [`migrations/001_initial_schema.sql`](file:///e:/Hackmitten3.0/migrations/001_initial_schema.sql).
4. Paste and click **Run**.
5. All 8 core tables (`services`, `dependencies`, `incidents`, `evidence`, `candidates`, `analysis_runs`, `timeline_events`, `evaluation_ground_truth`) and indexes will be created.

### 3. Configure the Application
In your `.env` file (or environment variables):
```env
STORAGE_BACKEND=supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key
SUPABASE_DB_URL=postgresql://postgres:[YOUR-PASSWORD]@db.your-project.supabase.co:5432/postgres
```

*Note: If `STORAGE_BACKEND=sqlite` is set (the default), AO-03 uses an embedded SQLite database (`data/ao03_telemetry.db`) that requires zero external configuration.*
