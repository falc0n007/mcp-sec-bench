# <server_id>

## What this pretends to be

One short paragraph. The cover story a user would believe if they installed it.

## What is wrong with it

For a vulnerable server: the class, where the flaw lives (file and symbol), and
why it is an instance of that class per the present-when test in
`docs/taxonomy.md`.

For a benign control: "Nothing. This is a control." Then say what it is a
control *for* -- which vulnerable server it mirrors, and which naive heuristic
it is built to catch out.

## How to reach it

The concrete call, with arguments. For runtime classes, the exact sequence
including any trigger.

## What a correct implementation looks like

Two or three lines showing the fix. Vulnerable servers only. This is what keeps
the corpus from reading as a how-to.
