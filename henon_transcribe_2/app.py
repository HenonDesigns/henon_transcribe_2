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
import pypandoc
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


@app.template_filter("seconds_to_time")
def seconds_to_time(seconds_str):
    seconds = float(seconds_str)
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    time_format = "{:0>2}:{:0>2}:{:05.2f}".format(int(hours), int(minutes), seconds)
    return time_format


@app.route("/")
def home():
    transcripts = Transcript.list_transcripts()
    return render_template("home.html", transcripts=transcripts)


@app.route("/data/<path:filename>", methods=["GET"])
def custom_data_static(filename):
    return send_from_directory("../data", filename)


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
        populate_database(slug, transcript.db_filepath, transcript.s3_output_key)

    segments_df = get_segments_pretty_merged(transcript.db_filepath)

    return render_template(
        "transcript_edit.html",
        transcript=transcript,
        segments_df=segments_df,
        recording_filename=transcript.recording_filepath,
    )


@app.route("/transcript/<slug>/table/html", methods=["GET"])
def transcript_table_html(slug):
    transcript = Transcript.load(slug=slug)

    if not os.path.exists(transcript.db_filepath):
        init_database(transcript.db_filepath)
        populate_database(transcript.db_filepath, transcript.s3_output_key)

    segments_df = get_segments_pretty_merged(transcript.db_filepath)
    unique_speakers_df = segments_df[
        ["speaker_label", "speaker_name"]
    ].drop_duplicates()
    return render_template(
        "transcript_table.html",
        segments_df=segments_df,
        unique_speakers_df=unique_speakers_df,
        transcript=transcript,
    )


@app.route("/transcript/<slug>/edit/segment/merge/<segment_id>", methods=["POST"])
def transcript_segment_merge(slug, segment_id):
    transcript = Transcript.load(slug=slug)

    bottom_id = int(segment_id)
    if int(segment_id) > 0:
        with duckdb.connect(transcript.db_filepath) as conn:
            top_id = conn.execute(
                """
            select id from segment
            where id < ?
            order by id desc
            limit 1;
            """,
                [bottom_id],
            ).fetchone()[0]

            conn.execute(
                f"""
            UPDATE segment
            SET transcript = (
                SELECT CONCAT(s1.transcript, ' ', s2.transcript)
                FROM segment AS s1, segment AS s2
                WHERE s1.id = ? AND s2.id = ?
            ),
            end_time = (
                SELECT s2.end_time
                FROM segment AS s2
                WHERE s2.id = ?
            )
            WHERE id = ?;
            """,
                [top_id, bottom_id, bottom_id, top_id],
            )

            conn.execute(
                f"""
            delete from segment
            where id = ?
            """,
                [bottom_id],
            )

            # TODO: decrement all ids by one
            conn.execute(
                """
            update segment
            set id = id::integer - 1
            where id > ?
            """,
                [segment_id],
            )

    return jsonify(
        {
            "action": "merge",
            "segment_id": segment_id,
            "merged_segment_id": str(int(segment_id) + 1),
        }
    )


@app.route("/transcript/<slug>/edit/segment/split/<segment_id>", methods=["POST"])
def transcript_segment_split(slug, segment_id):
    transcript = Transcript.load(slug=slug)
    segment_id = int(segment_id)
    split_data = request.get_json()
    print(split_data)

    with duckdb.connect(transcript.db_filepath) as conn:
        # update split segment
        conn.execute(
            """
        update segment
        set end_time = ?,
            transcript = ?
        where id = ?
        """,
            [
                split_data["split_time"],
                split_data["pre_split_text"],
                segment_id,
            ],
        )

        conn.execute(
            """
        update segment
        set id = id + 1
        where id > ?
        """,
            [segment_id],
        )

        conn.execute(
            """
        insert into segment (id, transcript, speaker_label, start_time, end_time)
        values (?, ?, ?, ?, ?)
        """,
            [
                segment_id + 1,
                split_data["post_split_text"],
                split_data["speaker_label"],
                split_data["split_time"],
                split_data["end_time"],
            ],
        )

        conn.commit()

    return jsonify(
        {
            "action": "merge",
            "segment_id": segment_id,
            "merged_segment_id": str(int(segment_id) + 1),
        }
    )


@app.route("/transcript/<slug>/edit/segment/text/update/<segment_id>", methods=["POST"])
def transcript_segment_update(slug, segment_id):
    transcript = Transcript.load(slug=slug)

    json_data = request.get_json()
    new_transcript = json_data["new_transcript"]

    with duckdb.connect(transcript.db_filepath) as conn:
        conn.execute(
            """
        update segment
        set transcript = ?
        where id = ?
        """,
            [new_transcript, segment_id],
        )

        conn.commit()

    return jsonify({"success": True})


@app.route(
    "/transcript/<slug>/edit/segment/<segment_id>/speaker/update/<speaker_label>",
    methods=["GET"],
)
def transcript_segment_speaker_update(slug, segment_id, speaker_label):
    transcript = Transcript.load(slug=slug)

    with duckdb.connect(transcript.db_filepath) as conn:
        conn.execute(
            """
        update segment
        set speaker_label = ?
        where id = ?
        """,
            [speaker_label, segment_id],
        )
        conn.commit()

    return jsonify({"success": True})


@app.route("/transcript/<slug>/sql", methods=["GET", "POST"])
def transcript_sql(slug):
    transcript = Transcript.load(slug=slug)

    sql = "Enter your query here..."
    results = """<p>Nothing yet...</p>"""
    if request.method == "POST":
        sql = request.form["sql"]
        with duckdb.connect(transcript.db_filepath) as conn:
            try:
                results = conn.execute(sql).fetch_df().to_html(index=False)
            except Exception as exc:
                results = f"<pre><code>{str(exc)}</code></pre>"

    return render_template(
        "sql.html",
        transcript=transcript,
        sql=sql,
        results=results,
    )


@app.route("/transcript/<slug>/export", methods=["GET", "POST"])
def transcript_export(slug):
    transcript = Transcript.load(slug=slug)
    segments_df = get_segments_pretty_merged(transcript.db_filepath)

    export_method = request.args.get("method", "html")

    if export_method == "html":
        return render_template("html_export.html", segments_df=segments_df)

    elif export_method == "word":
        export_html = render_template(
            "html_export.html",
            segments_df=segments_df,
        )

        # convert HTML to word doc
        output_file = f"/tmp/{transcript.slug}.docx"
        pypandoc.convert_text(
            export_html, to="docx", format="html", outputfile=output_file
        )
        return send_from_directory("/tmp", f"{transcript.slug}.docx")
    else:
        return "Export method not recognized."


def main():
    app.run(debug=True)


if __name__ == "__main__":
    main()
