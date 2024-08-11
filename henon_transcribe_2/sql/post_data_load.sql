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
        seg.transcript as transcript_original,
        case
            when st.segment_id is not null then st.transcript
            else seg.transcript
        end as transcript,
        seg.start_time,
        seg.end_time,
        (seg.start_time::float * 100)::integer * interval '0.01 sec' AS start_time_pretty,
        (seg.end_time::float * 100)::integer * interval '0.01 sec' AS end_time_pretty
    from segment seg
    inner join speaker spk on spk.speaker_label = seg.speaker_label
    left join segment_transcript_edit st on st.segment_id::integer = seg.id::integer
);


create view segment_merge_sets as (
    with recursive all_segs (segment_id, path, root_segment_id) as (
        select
            segment_id::integer as segment_id,
            array[segment_id::integer, segment_id::integer - 1] as path,
            segment_id::integer - 1 as root_segment_id
        from segment_merge
        union all
        select
            sm.segment_id::integer as segment_id,
            list_prepend(sm.segment_id::integer, all_segs.path) as path,
            least(sm.segment_id::integer - 1, all_segs.root_segment_id) as root_segment_id
        from segment_merge as sm, all_segs
        where sm.segment_id::integer - 1 = all_segs.segment_id::integer
    ),
    ranked as (
        select *,
        rank() over (partition by root_segment_id order by array_length(path, 1) desc) as rank
        from all_segs
    ),
    filtered as (
        select *
        from ranked
        where rank = 1
    )
    select f1.*
    from filtered f1
    where not exists (
        select 1
        from filtered f2
        where f1.path <> f2.path and f1.path <@ f2.path
    )
    order by f1.segment_id
);


create view segment_merged as (
    select
        min(sp.id::integer) as id,
        array_agg(sp.id::integer order by sp.id::integer) as segment_ids,
        (
            SELECT speaker_name
            FROM segment_pretty
            WHERE id::integer = sms.root_segment_id
            LIMIT 1
        ) as speaker_name,
        string_agg(sp.transcript_original, ' ' order by sp.id) as transcript_original,
        string_agg(sp.transcript, ' ' order by sp.id) as transcript,
        min(sp.start_time::numeric) as start_time,
        max(sp.end_time::numeric) as end_time
    from segment_pretty sp
    inner join segment_merge_sets sms on sp.id::integer = any(sms.path)
    group by sms.root_segment_id
);


create view segment_all as (
    with us as (
        select
            sp.id as segment_id,
            array[] as segment_ids,
            sp.speaker_name,
            sp.transcript_original,
            sp.transcript,
            sp.start_time,
            sp.end_time
        from segment_pretty sp
        where sp.id not in (select unnest(segment_ids) from segment_merged)

        union all

        select distinct
            sm.id as segment_id,
            sm.segment_ids,
            sm.speaker_name,
            sm.transcript_original,
            ste.transcript, -- used merged form, which is an "edit"
            sm.start_time,
            sm.end_time
        from segment_merged sm
        left join segment_transcript_edit ste on ste.segment_ids = sm.segment_ids
    )
    select * from us order by segment_id
);