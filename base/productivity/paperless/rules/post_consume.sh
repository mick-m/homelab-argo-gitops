#!/bin/sh
# Paperless post-consume script (PAPERLESS_POST_CONSUME_SCRIPT). Runs after each
# import, after the workflows, with DOCUMENT_ID etc. in the environment. Never
# fails the import: errors are logged and ignored.
cd /usr/src/paperless/src || exit 0
python3 manage.py shell < /usr/src/paperless/scripts/post_consume.py \
  || echo "post_consume: failed (ignored)"
exit 0
