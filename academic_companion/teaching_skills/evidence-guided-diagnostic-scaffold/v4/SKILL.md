---
id: evidence-guided-diagnostic-scaffold
version: 4
description: >
  v4 adds controlled dual Tool capability (code execution + science computation)
  on top of v3. v1-v3 historical turns and retry keep original behavior.
  Code and science tools are independently authorized per Turn;
  MCP total budget is 3 calls (code ≤ 2, science ≤ 3).
  Decision step budget raised from 5 to 8.
---

# Evidence-Guided Diagnostic Scaffold v4

## Method goals

Help learners progress based on course evidence, authorized learning state,
and authorized external tool observations. Safely use code execution and
science computation tools when explicitly authorized by the user for the
current Turn.

### This method does NOT

- Rote-recite or keyword-match to produce fixed outputs
- Conflate course references with learning state or tool observations
- Make unauthorized science or code tool calls
- Treat science results or code output as course facts or proof
- Generate code unrelated to the current question
- Call tools when they would not add learning value

## Execution sequence

1. **Identify task** by intent (not keywords): concept explanation, learner
   diagnosis, study planning, self-check, or other.
2. **Separate facts**: course content from evidence ledger only.
3. **Calibrate judgment**: confirmed vs provisional vs insufficient.
4. **Choose minimal sufficient scaffold**: 1-3 teaching moves.
5. **Code tools** (only when code_tool_authorized): 0-2 code_requests
   with language, source_code, stdin. Code must relate directly to the
   question. Max 12000 chars. No file/network/package/shell access.
6. **Science tools** (only when science_tool_authorized): 0-3
   science_requests for whitelisted tools (WolframAlpha, WolframContext).
   Must be empty when not authorized or not needed.
7. **Give one next action**.
8. **Self-check closing**: verify all factual claims have evidence citations,
   tool observations have provenance markers, no ungrounded assertions.

## Plan contract

```json
{
  "intent": "concept_explanation | learner_diagnosis | study_planning | self_check | other",
  "queries": ["1-3 distinct search queries"],
  "learning_context_use": "none | weakness | completion | both",
  "teaching_moves": ["1-3 from: focus, probe, explain, example, next_action, check"],
  "code_requests": [
    {"language": "python|java|cpp", "source_code": "...", "stdin": ""}
  ],
  "science_requests": [
    {"tool": "WolframAlpha|WolframContext", "arguments": {}}
  ]
}
```

Constraints:
- `code_requests`: 0-2 items; only when code_tool_authorized
- `science_requests`: 0-3 items; only when science_tool_authorized
- Total MCP calls (code + science): ≤ 3 per Turn
- `queries`: 1-3 distinct, 1-300 chars each
- `teaching_moves`: 1-3 distinct

## Answer contract

Ordered blocks (1-20):

- `direct_answer`: factual answer, requires ≥1 citation
- `explanation`: detailed explanation, requires ≥1 citation
- `example`: worked example, requires ≥1 citation
- `learning_diagnosis`: calibrated assessment, requires certainty, NO citations
- `next_action`: suggested next step, NO citations
- `check_question`: self-check question, NO citations
- `limitation`: honest statement of inability, NO citations
- `science_observation`: untrusted computation result, NO citations
- `code_observation`: untrusted code execution result, NO citations
- `memory_summary`: learning state summary

## Invariants

1. Science tool results and code execution output cannot directly create or
   modify mastery, weakness, memory, review items, practice feedback, or
   lesson completion.
2. Science tool failure or code execution failure requires a `limitation`
   block in the answer.
3. No authorization means no code_requests, no science_requests, and no
   code_observation or science_observation blocks.
4. v1-v3 historical turns never produce code or science requests.
5. Plan invalid fallback must not create any code or science requests.
6. Code must be directly related to the current question/teaching move.
7. Tool provenance is separate from course citation; they cannot impersonate
   each other.
8. Decision step budget: 8 (increased from v3's 5).
9. Evidence search: max 3 (unchanged).
10. MCP total: max 3 per Turn (code ≤ 2, science ≤ 3).
11. Tutor may use one remaining budget to correct its own code's
    compile/runtime error, but total code ≤ 2, MCP ≤ 3, steps ≤ 8.
