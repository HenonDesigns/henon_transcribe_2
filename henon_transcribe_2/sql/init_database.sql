CREATE MACRO natural_key(a) AS regexp_extract_all(
    a, '(\D+\d*|\d+)'
    ).list_transform(
    x -> regexp_extract(x, '(\D*)(\d*)', ['s', 'i'])
    ).list_transform(
    y -> {
      's': y.s,
      'i': CASE
             WHEN y.i = '' THEN -1
             ELSE CAST(y.i AS INTEGER)
           END
    }
);

create sequence merge_seq start 1;
create table segment_merge (
    id integer default nextval('merge_seq'),
    segment_id int
);

create sequence transcript_edit_seq start 1;
create table segment_transcript_edit (
    id integer default nextval('transcript_edit_seq'),
    segment_id int,
    segment_ids int[],
    transcript text
);