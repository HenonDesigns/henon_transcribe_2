import os.path

import duckdb
from flask import (
    Flask,
    render_template,
    jsonify,
    request,
    redirect,
    url_for,
    send_from_directory,
)
from werkzeug.utils import secure_filename

from henon_transcribe_2.core import (
    get_segments_pretty_merged,
    Transcript,
    upload_file_to_s3,
    start_job,
    init_database,
    populate_database,
)

app = Flask(__name__)


@app.route("/")
def home():
    transcripts = Transcript.list_transcripts()
    return render_template("home.html", transcripts=transcripts)


@app.route("/transcript/new", methods=["GET", "POST"])
def transcript_new():
    if request.method == "POST":
        name = request.form.get("name")
        transcript = Transcript.new(name)
        return redirect(url_for("transcript", slug=transcript.slug))

    return render_template("new_transcript.html")


@app.route("/transcript/<slug>")
def transcript(slug):
    transcript = Transcript.load(slug=slug)
    return render_template("transcript.html", transcript=transcript)


@app.route("/transcript/<slug>/upload", methods=["POST"])
def upload_transcript(slug):
    transcript = Transcript.load(slug=slug)

    if "audiofile" in request.files:
        file = request.files["audiofile"]
        if file.filename == "":
            raise Exception("No selected file")
        if file:
            _, file_extension = os.path.splitext(file.filename)
            filename = secure_filename(f"{slug}.recording{file_extension}")
            file.save(os.path.join("data", filename))

            # upload to S3
            upload_file_to_s3(transcript.recording_filepath)

            # start transcript job
            start_job(
                transcript.slug,
                transcript.s3_recording_uri,
                transcript.s3_output_key,
            )

            return redirect(url_for("transcript", slug=slug))
    else:
        raise Exception("No file part")


@app.route("/transcript/<slug>/edit")
def transcript_edit(slug):
    transcript = Transcript.load(slug=slug)

    # init db if needed
    if not os.path.exists(transcript.db_filepath):
        init_database(transcript.db_filepath)
        populate_database(transcript.db_filepath, transcript.s3_output_key)

    segments_df = get_segments_pretty_merged(transcript.db_filepath)
    return render_template(
        "transcript_edit.html",
        transcript=transcript,
        segments_df=segments_df,
        recording_filename=transcript.recording_filepath,
    )


@app.route("/data/<path:filename>", methods=["GET"])
def custom_data_static(filename):
    return send_from_directory("../data", filename)


@app.route("/transcript/<slug>/edit/segment/merge/<segment_id>", methods=["POST"])
def transcript_segment_merge(slug, segment_id):
    transcript = Transcript.load(slug=slug)

    if int(segment_id) > 0:
        with duckdb.connect(transcript.db_filepath) as conn:
            conn.execute(f"""
            insert into segment_merge (segment_id) values ({segment_id})
            """)

    return jsonify(
        {
            "action": "merge",
            "segment_id": segment_id,
            "merged_segment_id": str(int(segment_id) + 1),
        }
    )


@app.route("/transcript/<slug>/edit/segment/unmerge/<segment_id>", methods=["POST"])
def transcript_segment_unmerge(slug, segment_id):
    transcript = Transcript.load(slug=slug)

    with duckdb.connect(transcript.db_filepath) as conn:
        conn.execute(f"""
        delete from segment_merge
        where segment_id in (
            select unnest(path) 
            from segment_merge_sets
            where root_segment_id = {segment_id}
        )
        """)

    return jsonify(
        {
            "action": "unmerge",
            "segment_id": segment_id,
        }
    )


@app.route("/transcript/<slug>/edit/segment/update", methods=["POST"])
def transcript_segment_update(slug):
    json_data = request.get_json()

    segment_id = json_data["segment_id"]
    new_transcript = json_data["new_transcript"]

    transcript = Transcript.load(slug=slug)
    with duckdb.connect(transcript.db_filepath) as conn:
        conn.execute(
            """
        UPDATE segment
        SET transcript = ?
        WHERE id::text = ?
        """,
            (new_transcript, segment_id),
        )
        conn.commit()

    return jsonify(
        {"action": "update", "segment_id": segment_id, "new_transcript": new_transcript}
    )


def main():
    app.run(debug=True)


if __name__ == "__main__":
    main()
