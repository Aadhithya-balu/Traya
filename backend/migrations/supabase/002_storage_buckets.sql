-- 002_storage_buckets.sql - TRAYA on Supabase
--
-- Run this in the Supabase SQL editor AFTER 001_extensions.sql.
-- Optional: the app does not reference Supabase Storage yet, and Phase 3's
-- image path still writes through the API. Run it now so the buckets exist
-- before anything depends on them.
--
-- Deliberately NOT public. `public = false` on every bucket is the setting
-- that matters, because a public bucket is readable by URL with no
-- authorization at all - and the objects in question are face photographs and
-- medical documents. TRAYA serves images through an authorized endpoint, never
-- by handing out a storage URL.
--
-- The migration plan calls for "retention policies". Those are Storage object
-- lifecycle rules, configured in the dashboard under Storage -> Buckets ->
-- <bucket> -> Settings, not in this file; there is no portable SQL for them
-- and inventing a table that looks like one would be worse than not having it.
-- Treat the retention work as outstanding until it is done in the dashboard.
--
-- Idempotent: ON CONFLICT DO NOTHING. Re-running changes nothing.

-- Face captures from the emergency flow. Short retention: these are the most
-- sensitive objects in the system and are useful only for the duration of an
-- incident response.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'emergency-captures',
  'emergency-captures',
  false,
  6291456,
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do nothing;

-- Enrollment samples, before they are committed to a template.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'enrollment-samples',
  'enrollment-samples',
  false,
  6291456,
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do nothing;

-- The 6 MiB limit matches MAX_UPLOAD_BYTES in app/config/settings.py and
-- ALLOWED_IMAGE_MIMES matches its default. If you change one, change it in
-- both places: a bucket that is more permissive than the API is a way in, and
-- a bucket that is stricter breaks uploads with an opaque error.

-- Verify:
--   select id, public, file_size_limit from storage.buckets order by id;
-- Expect 2 rows, `public` false on both, file_size_limit 6291456.
