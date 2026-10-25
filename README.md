# This folder contains the configuration needed to run the Fildah stack (`api`, `fildah-web`, and `care-web`) on your own Virtual Private Server (VPS).

Source documents and other Django media use the persistent `django_media`
volume by default. To move media to S3 or Cloudflare R2, copy the
`MEDIA_STORAGE_BACKEND` and `MEDIA_S3_*` settings from `.env.example` into the
host-managed `.env`. Never commit the real credentials.
