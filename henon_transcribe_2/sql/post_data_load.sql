create table speaker as (
    select distinct
        speaker_label,
        ('Participant ' || split_part(speaker_label, '_', 2))::text as speaker_name
    from segment
    order by natural_key(speaker_label)
);


create view segment_pretty as (
    select
        seg.id,
        spk.speaker_label,
        spk.speaker_name,
        seg.transcript,
        seg.start_time,
        seg.end_time,
        (seg.start_time::float * 100)::integer * interval '0.01 sec' AS start_time_pretty,
        (seg.end_time::float * 100)::integer * interval '0.01 sec' AS end_time_pretty
    from segment seg
    inner join speaker spk on spk.speaker_label = seg.speaker_label
);

create table segment_backup as (
    select * from segment
)