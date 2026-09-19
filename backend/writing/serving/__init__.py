"""The writing product's read side: the teacher console's queue, home, trait profile.

Reads the writing modules' tables with SQL and imports none of them — the same producer/serving
split SIP's `serving` keeps, drawn again inside this product so the table stays the only seam.
The write side (release, override, resolve) lives in `writing.scoring`, which owns those tables.
"""
