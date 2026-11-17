"""Corpus pipeline: Easy German → scored, word-timed clip candidates.

Four stages (plan §8):

* ``manifest`` — flat playlist fetch → ``videos`` (stage A, no downloads).
* ``captions`` — json3 subtitle fetch → ``words`` (stage B, subtitles only).
* ``mine`` — segment + score word streams → ``content/corpus/clips.jsonl`` (stage C).
* ``score`` — pure teachability scoring shared by the mining stage and tests.

Stage D (human promotion) is deliberately not automated. Every mined clip has
``review="pending"``; nothing here auto-generates lessons (invariant, plan §8.5).

Network fetchers in ``manifest`` and ``captions`` are injectable so the unit
tests never touch YouTube. Mining itself is pure over SQLite word rows.
"""
