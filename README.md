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
- show timestamp as `hh:mm:ss`
- show segments ids as ranage like `[0..14]`
- edit speaker (dropdown?) --> _always_ dropdown
- undo merges
- edit text in a merged segment
- export to word
- "notes" field for each segment
  - can they be exported as comments in the word doc
