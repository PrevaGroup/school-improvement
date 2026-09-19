# delivery - working notes

The module owns `artifact_delivery` and nothing else. It READS `artifact`,
`artifact_composition`, `intake_file` and `intake_manifest` with SQL and imports
none of them.

Two rules worth keeping in mind before changing anything here:

- An attempt is a fact. Nothing updates a row; a retry appends one that points at
  the attempt it follows, and the failure stays in the record. That is what a
  teacher needs when a student says they never got anything.
- The `released` check is a trigger, not an if-statement. This module is one way
  to reach the table and a script is another.
