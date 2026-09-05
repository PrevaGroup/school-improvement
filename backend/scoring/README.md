# scoring

The immutable record of what was scored, by whom, under which configuration, and what a teacher
then decided. Three tables and a state machine enforced in the database.

Read `CONTRACT.md` before changing a table shape. The short version: scores append and never
update, only a teacher can release, and an override is not a supersession.

Design: the SIP teacher-subsystem expansion plan §6, and agentic-scoring-pipeline-design v0.06
§3.2 (states) and §6.1 (the score record).
