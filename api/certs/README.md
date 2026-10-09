# Supabase public database root CA

`supabase-prod-ca-2021.crt` was downloaded over verified HTTPS from the URL
used by Supabase's official dashboard configuration on 2026-10-10:

https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt

Source: `apps/studio/hooks/custom-content/custom-content.json` in
https://github.com/supabase/supabase

SHA-256 of the downloaded PEM bytes:
`700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`

This is a public trust anchor, not a client certificate or private key.
`DATABASE_SSL_CA_FILE` adds this CA to the default trust store for PostgreSQL
connections only. Certificate and hostname verification remain required.
