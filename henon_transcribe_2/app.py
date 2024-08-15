import os.path
import time

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


@app.route("/transcript/<slug>/table/html", methods=["GET"])
def transcript_table_html(slug):
    transcript = Transcript.load(slug=slug)
    if not os.path.exists(transcript.db_filepath):
        init_database(transcript.db_filepath)
        populate_database(transcript.db_filepath, transcript.s3_output_key)
    segments_df = get_segments_pretty_merged(transcript.db_filepath)
    return render_template(
        "transcript_table.html",
        segments_df=segments_df,
        transcript=transcript,
    )


@app.route("/data/<path:filename>", methods=["GET"])
def custom_data_static(filename):
    return send_from_directory("../data", filename)


@app.route("/transcript/<slug>/edit/segment/merge/<segment_id>", methods=["POST"])
def transcript_segment_merge(slug, segment_id):
    transcript = Transcript.load(slug=slug)

    segment_id = int(segment_id)
    if int(segment_id) > 0:
        with duckdb.connect(transcript.db_filepath) as conn:
            # add segment merge
            conn.execute(f"""
            insert into segment_merge (segment_id) values ({segment_id})
            """)

            # add new transcript edit for merge
            segment_ids = conn.execute(
                """
            select segment_ids
            from segment_transcript_edit
            where ? = any(segment_ids)
            limit 1
            """,
                [segment_id],
            ).fetchone()
            if segment_ids:
                segment_ids = segment_ids[0]
                segment_ids.insert(0, segment_id - 1)
            else:
                segment_ids = [segment_id - 1, segment_id]
            segment_ids = f"array{segment_ids}"

            query = f"""
            insert into segment_transcript_edit (segment_ids, transcript) values (
                {segment_ids},
                (
                    with sub_edit as (
                        select transcript from segment_transcript_edit
                        where segment_ids <@ {segment_ids}
                        order by array_length(segment_ids) desc
                    ),
                    merged as (
                        select transcript from segment_merged
                        where segment_ids = {segment_ids}
                        limit 1
                    )
                    select
                        case when (select count(*) from sub_edit) > 0 then
                            concat((select transcript from segment_pretty where id = {segment_id-1}), ' ', (select transcript from sub_edit))
                        else
                            (select transcript from merged limit 1)
                        end as transcript
                )
            );
            """
            conn.execute(query)

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
        segment_ids = transcript.get_merged_segment_ids(conn, segment_id)
        if segment_ids:
            target_column = "segment_ids"
            target_value = f"array{segment_ids}"
        else:
            target_column = "segment_id"
            target_value = segment_id

        conn.execute(f"""
        delete from segment_merge
        where segment_id in (
            select unnest(path) 
            from segment_merge_sets
            where root_segment_id = {segment_id}
        )
        """)

        delete_query = f"""
        delete from segment_transcript_edit
        where {target_column} <@ {target_value};
        """
        print(delete_query)
        conn.execute(delete_query)

    return jsonify(
        {
            "action": "unmerge",
            "segment_id": segment_id,
        }
    )


@app.route("/transcript/<slug>/edit/segment/text/update/<segment_id>", methods=["POST"])
def transcript_segment_update(slug, segment_id):
    transcript = Transcript.load(slug=slug)

    json_data = request.get_json()
    new_transcript = json_data["new_transcript"]

    with duckdb.connect(transcript.db_filepath) as conn:
        segment_ids = transcript.get_merged_segment_ids(conn, segment_id)
        if segment_ids:
            target_column = "segment_ids"
            target_value = segment_ids
        else:
            target_column = "segment_id"
            target_value = segment_id

        conn.execute(
            f"""
                delete from segment_transcript_edit where {target_column} = ?;
                """,
            [target_value],
        )
        conn.execute(
            f"""
                insert into segment_transcript_edit ({target_column}, transcript)
                values (?, ?);
                """,
            [
                target_value,
                new_transcript,
            ],
        )

        conn.commit()

    # TODO: update this response...
    return jsonify(
        {"action": "update", "segment_id": segment_id, "new_transcript": new_transcript}
    )


@app.route("/transcript/<slug>/edit/segment/text/reset/<segment_id>", methods=["POST"])
def transcript_segment_reset(slug, segment_id):
    transcript = Transcript.load(slug=slug)
    with duckdb.connect(transcript.db_filepath) as conn:
        segment_ids = transcript.get_merged_segment_ids(conn, segment_id)
        if segment_ids:
            target_column = "segment_ids"
            target_value = segment_ids
        else:
            target_column = "segment_id"
            target_value = segment_id

        conn.execute(
            f"""
        delete from segment_transcript_edit where {target_column} = ?;
        """,
            [target_value],
        )
        conn.commit()

    # TODO: update this response...
    return jsonify({"action": "reset", "segment_id": segment_id})


def main():
    app.run(debug=True)


if __name__ == "__main__":
    main()
