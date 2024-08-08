import glob
import json
import os.path

from attrs import define, field
import boto3
import duckdb
import pandas as pd
from slugify import slugify

S3_BUCKET = os.environ.get("S3_BUCKET", "henon-transcribe")
TRANSCRIPTS_JSON = os.environ.get("TRANSCRIPTS_JSON", "data/transcripts.json")

session = boto3.Session(region_name="us-east-1")
transcribe_client = session.client("transcribe")
s3_client = session.client("s3")
s3_resource = session.resource("s3")


def upload_file_to_s3(file_path, bucket=S3_BUCKET):
    key = file_path
    s3_client.upload_file(file_path, bucket, key)
    print(f"File {file_path} uploaded successfully to {bucket}/{key}")
    return f"s3://{bucket}/{key}"


def start_job(job_name, s3_audio_uri, s3_output_key, max_speakers=18):
    return transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        LanguageCode="en-US",
        Media={
            "MediaFileUri": s3_audio_uri,
        },
        OutputBucketName=S3_BUCKET,
        OutputKey=s3_output_key,
        Settings={
            "ShowSpeakerLabels": True,
            "MaxSpeakerLabels": max_speakers,
            "ShowAlternatives": False,
        },
    )


def check_job(job_name):
    return transcribe_client.get_transcription_job(TranscriptionJobName=job_name)


def get_job_output(s3_output_key):
    transcript_object = s3_resource.Object(S3_BUCKET, s3_output_key)
    file_content = transcript_object.get()["Body"].read().decode("utf-8")
    return json.loads(file_content)


def init_database(db_filepath):
    with duckdb.connect(db_filepath) as conn, open(
        "henon_transcribe_2/sql/init_database.sql"
    ) as f:
        conn.execute(f.read())
        conn.commit()


def populate_database(db_filepath, s3_output_key):
    results = get_job_output(s3_output_key)["results"]

    with duckdb.connect(db_filepath) as conn:
        # create "segments" table
        audio_segments_df = pd.DataFrame(results["audio_segments"])
        conn.execute("""create table segment as select * from audio_segments_df;""")

        # create "items" table
        items_df = pd.DataFrame(results["items"])
        conn.execute("""create table item as select * from items_df;""")

        with open("henon_transcribe_2/sql/post_data_load.sql") as f:
            conn.execute(f.read())

        conn.commit()


def get_segments_pretty_merged(db_filepath):
    with duckdb.connect(db_filepath) as conn:
        conn.execute("""select * from segment_all;""")
        df = conn.fetch_df()
    return df


def rebuild(slug):
    os.remove(f"data/{slug}.duckdb")
    init_database()
    populate_database()


@define
class Transcript:
    slug: str = field()

    @property
    def slug(self):
        return slugify(self.name)

    @property
    def info(self):
        with open(f"data/{self.slug}.info.json") as f:
            return json.load(f)

    @property
    def name(self):
        return self.info["name"]

    @property
    def info_filepath(self):
        return f"data/{self.slug}.info.json"

    @property
    def recording_filepath(self):
        if recordings := glob.glob(f"data/{self.slug}.recording.*"):
            return recordings[0]
        return None

    @property
    def raw_filepath(self):
        return f"data/{self.slug}.raw.json"

    @property
    def db_filepath(self):
        return f"data/{self.slug}.db.duckdb"

    @property
    def s3_recording_uri(self):
        return f"s3://{S3_BUCKET}/{self.recording_filepath}"

    @property
    def s3_output_key(self):
        return self.raw_filepath

    @property
    def s3_output_uri(self):
        return f"s3://{S3_BUCKET}/{self.s3_output_key}"

    @classmethod
    def list_transcripts(cls):
        slugs = [
            f.removeprefix("data/").removesuffix(".info.json")
            for f in glob.glob(f"data/*.info.json")
        ]
        return [cls(slug=slug) for slug in slugs]

    @classmethod
    def new(cls, name):
        slug = slugify(name)
        with open(f"data/{slug}.info.json", "w") as f:
            f.write(json.dumps({"slug": slug, "name": name}))
        return cls(slug=slug)

    @classmethod
    def load(cls, slug=None, name=None):
        if slug is None and name is None:
            raise Exception("slug or name must be provided")
        if name:
            slug = slugify(name)
        return cls(slug=slug)

    def get_status(self):
        return check_job(self.slug)

    @property
    def job_status(self):
        return self.get_status()["TranscriptionJob"]["TranscriptionJobStatus"]
