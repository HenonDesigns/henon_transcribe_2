# Henon Transcribe 2

## Installation

```shell
poetry install
```

## Env Vars
```shell
# Required
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# Optional
S3_BUCKET="henon-transcribe"
TRANSCRIPTS_JSON="data/transcripts.json"
```

## TODO
- edit text in a merged segment
  - the answer here... is when segments are merged, to write a new materialzied `segment_merge` row
  - then we can edit that row, and it's ironclad
  - we could use the view to _create_ the row?  maybe still value that way?
  - then if you unmerge, you just drop that row, and you get the originals back
  - I reckon... this would also "unroll" the merges organically!
- "notes" field for each segment
  - can they be exported as comments in the word doc
- export to word
- show timestamp as `hh:mm:ss`
- edit speaker
