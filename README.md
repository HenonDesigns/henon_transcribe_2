# Henon Transcribe 2

## Installation

```shell
brew install pandoc
```

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
```

## TODO
- "notes" field for each segment
  - can they be exported as comments in the word doc
- add speakers, even when dropped from unique list
- modify timestamps for segment
  - start: update previous segment end time
  - end: update next segment start time
