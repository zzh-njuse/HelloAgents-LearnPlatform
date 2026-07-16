"""Stage 3 Slice 3 offline eval harness.

Default mode is fully offline: it drives the real Course Architect, Lesson
Writer and Tutor generation paths with an injected fake provider and asserts the
deterministic hard gates. It never contacts an external model in offline mode and
never records prompts, answers, evidence, source text, paths or provider config.
"""
