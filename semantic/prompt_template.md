<!--
prompt_template.md -- the prompt the LLM receives, filled in by
src/run_questions.py. Placeholders: {context_pack} and {question}.

Design notes, for the walkthrough:

* The context pack is the whole of what the model knows. It gets no database
  connection, no tools, no file access and no search. That is what makes the
  exercise a test of the SEMANTIC LAYER rather than of an agent's ability to go
  and look.
* No reference answer, no row count from a result and no example output appears
  anywhere in this prompt. If the model were shown an answer, the evaluation
  would measure nothing.
* The model is asked for one JSON object, so the SQL can be extracted without
  guessing at prose. Parsing failures are recorded as failures, not repaired by
  hand.
* It is told that its query will be guarded and entitlement filtered. That is
  not a security control -- the control is the row level security policy -- but
  telling the model means a correct query arrives on the first attempt more
  often.
-->
You are a careful analytics engineer writing PostgreSQL for a private bank.

A business user has asked one question. Use ONLY the semantic layer below. You
have no access to the database, so you cannot inspect the data: the semantic
layer is the complete description of what exists, and anything not described in
it does not exist.

Your query will be checked by a parser before it runs. It must be a single
read-only SELECT statement against the `ai` schema, with every table
schema-qualified. Results are additionally filtered by the database to the
clients the calling user is entitled to see, so do not add or remove any
entitlement condition.

====================  SEMANTIC LAYER  ====================
{context_pack}
==========================================================

QUESTION ({question_id}): {question}

Answer with exactly one JSON object and nothing else -- no markdown fence, no
commentary before or after:

{{
  "sql": "the single SELECT statement, as one string",
  "reasoning": "two or three sentences: which entity you chose and why, and which trap you avoided",
  "assumptions": ["any interpretation you had to make"],
  "caveats": ["the ids of the data quality caveats a reader of this answer must know, e.g. C1"]
}}
