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