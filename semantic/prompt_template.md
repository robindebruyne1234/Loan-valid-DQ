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
* It must also return an "ir": a small statement of the metric, periods,
  grouping and filters it intends. src/sql_ir.py verifies the SQL against that
  intent before execution and recomputes the certified metric from it after
  (D029). A guard pass says a query may run; only that verification says it
  computes what was declared.
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

Alongside the SQL, state what it computes as an "ir" object. The application
checks the SQL against your ir BEFORE it runs, and refuses it when they differ:
the same certified metric on its own entity and counting grain; a filter on the
metric's time_column that selects every period in "periods" and nothing else
("from" is the first day included, "to" the first day NOT included); a GROUP BY
for every entry in "group_by", returning one row per group (never one column
per value); the "filters" you list and no others; only the metric's permitted
joins; a LIMIT only when you set "limit". Every column you use must exist on
the entity you take it from. If no certified metric answers the question, set
"metric" to null and explain why in "assumptions": the application will then
decline rather than guess.

Answer with exactly one JSON object and nothing else -- no markdown fence, no
commentary before or after:

{{
  "sql": "the single SELECT statement, as one string",
  "ir": {{
    "metric": "the certified metric you compute, a name from 'Certified metrics'",
    "entity": "that metric's entity, e.g. ai.loan",
    "counting_grain": "that metric's counting_grain, e.g. loan_id",
    "time": null or {{"column": "the metric's time_column", "periods": [{{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}}]}},
    "group_by": ["columns you group by, or year / quarter / month of the time_column"],
    "filters": [{{"column": "a column", "op": "=", "value": "a value"}}],
    "order": null or "asc" or "desc",
    "limit": null or the number of rows asked for
  }},
  "reasoning": "two or three sentences: which entity you chose and why, and which trap you avoided",
  "assumptions": ["any interpretation you had to make"],
  "caveats": ["the ids of the data quality caveats a reader of this answer must know, e.g. C1"]
}}
