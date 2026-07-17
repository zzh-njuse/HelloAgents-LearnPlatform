"""Stage 4 Slice 1 offline practice eval harness.

Default mode is fully offline: it drives the real Exercise Author and Answer
Grader paths with an injected fake provider and asserts the deterministic hard
gates. It never contacts an external model and never records prompts, answers,
rubrics, feedback, evidence, source text, paths or provider config.
"""
