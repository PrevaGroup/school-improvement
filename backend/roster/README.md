# roster

Who is in which class, and who may see it. Four tables and one SQL function.

The function is the interesting part: `roster_visible_sections()` resolves section membership for
the current principal, in SQL, so an RLS policy can use it. Read `CONTRACT.md` before changing a
table shape — particularly the two policy questions this module deliberately leaves open.

Design: the SIP teacher-subsystem expansion plan §7.
