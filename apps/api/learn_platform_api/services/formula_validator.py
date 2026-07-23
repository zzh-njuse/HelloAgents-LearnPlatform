"""
Server-side formula validation for learning content.

Per Spec 004 §4.1 and ADR 006 §2.2:
- Validates $...$ and $$...$$ delimiter pairing
- Enforces expression length limits
- Checks command whitelist (rejects dangerous/unknown commands)
- Rejects raw HTML, scripts, event attributes, arbitrary URLs
- Allows one repair attempt; still failing = artifact failure

This module is used by Lesson/Practice/Tutor artifact validators.
It does NOT connect to databases or MCP services.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_EXPRESSION_LENGTH = 2000
MAX_TOTAL_CONTENT_LENGTH = 100_000

# Inline math: $...$ (not $$)
INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
# Display math: $$...$$
DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)

# Dangerous patterns that must never appear in math expressions
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<[a-zA-Z]"),          # Raw HTML tags
    re.compile(r"\bon\w+\s*="),        # Event handlers
    re.compile(r"javascript:", re.I),   # JS URL scheme
    re.compile(r"\\href"),             # KaTeX \href (needs trust=true)
    re.compile(r"\\url"),              # KaTeX \url
    re.compile(r"\\def\b"),            # TeX macro definitions
    re.compile(r"\\newcommand\b"),     # LaTeX newcommand
    re.compile(r"\\renewcommand\b"),   # LaTeX renewcommand
    re.compile(r"\\let\b"),            # TeX \let
]

# Allowed command prefixes beyond standard KaTeX built-ins
ALLOWED_EXTRA_PREFIXES = {"\\ce"}  # mhchem

# Deliberately finite subset used by learning content. KaTeX supports many more
# commands, but accepting every renderer command would not satisfy the product
# contract's unknown-command boundary.
ALLOWED_COMMANDS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu", "pi", "rho", "sigma", "tau", "phi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Pi", "Sigma", "Phi", "Omega",
    "frac", "dfrac", "tfrac", "sqrt", "sum", "prod", "int", "iint", "iiint", "lim", "infty", "partial", "nabla",
    "sin", "cos", "tan", "log", "ln", "exp", "min", "max", "arg",
    "cdot", "times", "div", "pm", "mp", "le", "leq", "ge", "geq", "ne", "neq", "approx", "equiv", "propto",
    "to", "rightarrow", "leftarrow", "leftrightarrow", "Rightarrow", "Leftarrow", "Leftrightarrow",
    "in", "notin", "subset", "subseteq", "supset", "supseteq", "cup", "cap", "forall", "exists",
    "text", "mathrm", "mathbf", "mathit", "mathbb", "mathcal", "operatorname", "left", "right",
    "overline", "underline", "hat", "bar", "vec", "overbrace", "underbrace",
    "begin", "end", "matrix", "pmatrix", "bmatrix", "cases", "array",
    "quad", "qquad", "ldots", "cdots", "vdots", "ddots", "degree", "circ", "%", "ce",
}
COMMAND_RE = re.compile(r"\\([A-Za-z]+|%)")
RAW_HTML_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FormulaValidationResult:
    """Result of formula content validation."""
    valid: bool
    errors: list[str]
    """Human-readable error messages (safe for logs, not for client exposure)."""
    repaired_content: str | None = None
    """If a single repair was applied, the repaired content; None otherwise."""


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def _extract_math_expressions(content: str) -> list[str]:
    """Extract all math expressions from content (both inline and display)."""
    expressions: list[str] = []
    for match in DISPLAY_MATH_RE.finditer(content):
        expressions.append(match.group(1))
    for match in INLINE_MATH_RE.finditer(content):
        expressions.append(match.group(1))
    return expressions


def _check_expression(expr: str) -> str | None:
    """
    Check a single math expression for safety.
    Returns an error message if unsafe, None if safe.
    """
    if len(expr) > MAX_EXPRESSION_LENGTH:
        return f"Expression exceeds max length ({len(expr)} > {MAX_EXPRESSION_LENGTH})"
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(expr):
            return f"Expression contains dangerous pattern"
    unknown = sorted({match.group(1) for match in COMMAND_RE.finditer(expr)} - ALLOWED_COMMANDS)
    if unknown:
        return "Expression contains an unsupported command"
    return None


def _check_delimiter_pairing(content: str) -> list[str]:
    """
    Check that $ and $$ delimiters are properly paired.
    Returns list of error messages for unpaired delimiters.
    """
    errors: list[str] = []

    if RAW_HTML_RE.search(content):
        errors.append("Raw HTML is not allowed")

    # Check $$ pairing first (display math takes precedence)
    # Remove all properly paired $$ first
    reduced = DISPLAY_MATH_RE.sub("", content)

    # Count remaining $ signs (should be even for proper inline pairing)
    dollar_positions = [i for i, ch in enumerate(reduced) if ch == "$"]
    if len(dollar_positions) % 2 != 0:
        errors.append("Unpaired $ delimiter in content")

    return errors


def validate_formula_content(content: str) -> FormulaValidationResult:
    """
    Validate learning content with math formulas.

    Per Spec 004 §4.1:
    - Check delimiter pairing
    - Check expression length
    - Check command whitelist
    - Reject raw HTML, scripts, URLs, macros
    - Allow one repair attempt
    - Still failing = artifact failure

    Returns FormulaValidationResult with valid=True if all checks pass.
    """
    if not content:
        return FormulaValidationResult(valid=True, errors=[])

    if len(content) > MAX_TOTAL_CONTENT_LENGTH:
        return FormulaValidationResult(
            valid=False,
            errors=[f"Content exceeds max total length ({len(content)} > {MAX_TOTAL_CONTENT_LENGTH})"],
        )

    errors: list[str] = []

    # 1. Delimiter pairing
    errors.extend(_check_delimiter_pairing(content))

    # 2. Extract and check each math expression
    expressions = _extract_math_expressions(content)
    for i, expr in enumerate(expressions):
        err = _check_expression(expr)
        if err:
            errors.append(f"Math expression {i + 1}: {err}")

    if not errors:
        return FormulaValidationResult(valid=True, errors=[])

    # 3. One repair attempt: try to fix unpaired delimiters by removing
    #    the offending $ signs. This is a best-effort repair.
    repaired = _attempt_repair(content)
    if repaired is not None:
        # Re-validate the repaired content
        repair_errors: list[str] = []
        repair_errors.extend(_check_delimiter_pairing(repaired))
        repaired_exprs = _extract_math_expressions(repaired)
        for i, expr in enumerate(repaired_exprs):
            err = _check_expression(expr)
            if err:
                repair_errors.append(f"Math expression {i + 1}: {err}")
        if not repair_errors:
            return FormulaValidationResult(
                valid=True, errors=[], repaired_content=repaired
            )

    return FormulaValidationResult(valid=False, errors=errors)


def _attempt_repair(content: str) -> str | None:
    """
    Attempt a single repair: remove trailing unpaired $ signs.
    Returns repaired content or None if repair is not applicable.
    """
    # Simple repair: if there's exactly one unpaired $, remove it
    reduced = DISPLAY_MATH_RE.sub("", content)
    dollar_count = reduced.count("$")
    if dollar_count % 2 == 1:
        # Remove the last unpaired $
        last_dollar = content.rfind("$")
        # Make sure it's not part of a $$
        if last_dollar > 0 and content[last_dollar - 1] == "$":
            return None  # Don't try to repair $$ mismatches
        if last_dollar < len(content) - 1 and content[last_dollar + 1] == "$":
            return None
        return content[:last_dollar] + content[last_dollar + 1:]
    return None
