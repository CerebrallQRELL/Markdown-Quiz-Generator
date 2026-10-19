"""Interactive coding questions: safe variation, editable blanks and grading."""
import ast
import random
import re

from ..services.sandbox import run_in_sandbox
# Compatibility imports for callers written before selection.py.
from .selection import eligible, filter_questions as matching


class InvalidQuestionError(ValueError):
    """A source program cannot be used as an exercise."""


class NoOutputError(InvalidQuestionError):
    """A valid silent program is not an output-based learning question."""



def varied_code(source, rng=None):
    """Vary only numeric call inputs to proven straight-line arithmetic functions.

    No loops, indexing, division, sentinels, comparisons, APIs or algorithm
    constants are changed. Unsupported examples keep their original inputs.
    """
    rng = rng or random
    tree = ast.parse(source)
    safe = {}
    allowed = (ast.BinOp, ast.UnaryOp, ast.Name, ast.Constant, ast.Add, ast.Sub,
               ast.Mult, ast.UAdd, ast.USub, ast.Load)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
            continue
        names = {a.arg for a in node.args.args}
        expression = node.body[0].value
        if expression is None or node.decorator_list or node.args.defaults or node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
            continue
        if all(isinstance(n, allowed) and (not isinstance(n, ast.Name) or n.id in names)
               and (not isinstance(n, ast.Constant) or type(n.value) in (int, float)) for n in ast.walk(expression)):
            safe[node.name] = len(names)
    changes = []
    # Only direct calls printed at module scope are demonstration inputs.
    for statement in tree.body:
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name) and statement.value.func.id == 'print'):
            continue
        for call in statement.value.args:
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in safe
                    and len(call.args) == safe[call.func.id] and not call.keywords):
                continue
            if not all(isinstance(a, ast.Constant) and type(a.value) is int and 1 <= a.value <= 100 for a in call.args):
                continue
            for argument in call.args:
                old = argument.value
                argument.value = rng.choice([n for n in range(1, 21) if n != old])
                changes.append(dict(line=argument.lineno, before=old, after=argument.value))
    return (ast.unparse(tree) if changes else source), changes


def make_blanks(code, difficulty, rng=None):
    rng = rng or random
    tree = ast.parse(code)
    nodes = list(ast.walk(tree))
    if difficulty == 'easy':
        candidates = [n for n in nodes if isinstance(n, (ast.Constant, ast.Name)) and not isinstance(getattr(n, 'ctx', None), ast.Store)]
    else:
        candidates = [n for n in nodes if isinstance(n, (ast.BinOp, ast.Compare, ast.BoolOp, ast.Name))
                      and not isinstance(getattr(n, 'ctx', None), ast.Store)]
    if not candidates:
        candidates = [n for n in nodes if isinstance(n, ast.Constant)]
    raw = code.encode('utf-8')
    lines = raw.splitlines(keepends=True)
    spans = []
    rng.shuffle(candidates)
    for node in candidates:
        start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
        end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
        if any(start < b and end > a for a, b in spans):
            continue
        spans.append((start, end))
        if len(spans) >= {'easy': 1, 'medium': 2, 'hard': 3}[difficulty]:
            break
    if not spans:
        raise ValueError('This block has no suitable editable expressions.')
    answers, blanks, pieces, cursor = {}, [], [], 0
    for index, (start, end) in enumerate(sorted(spans), 1):
        identity = f'blank_{index}'
        marker = f'<BLANK_{index}>'
        answer = raw[start:end].decode('utf-8')
        answers[identity] = answer
        blanks.append(dict(id=identity, marker=marker, multiline='\n' in answer))
        pieces.extend([raw[cursor:start].decode('utf-8'), marker])
        cursor = end
    pieces.append(raw[cursor:].decode('utf-8'))
    return dict(blank_code=''.join(pieces), blanks=blanks, solutions=answers)


def reconstruct(question, answers):
    expected = {b['id'] for b in question['blanks']}
    if not isinstance(answers, dict) or set(answers) != expected or not all(isinstance(v, str) and len(v) <= 10000 for v in answers.values()):
        raise ValueError('Provide an answer for each blank.')
    # One-pass substitution means inserted text cannot overwrite another blank.
    markers = {b['marker']: answers[b['id']] for b in question['blanks']}
    if not markers:
        return question['blank_code']
    return re.sub('|'.join(re.escape(m) for m in markers), lambda m: markers[m.group()], question['blank_code'])


def validate_imports(value):
    if not isinstance(value, str) or len(value) > 4000:
        raise ValueError('Python imports must be text up to 4,000 characters.')
    try:
        tree = ast.parse(value)
    except SyntaxError as exc:
        raise ValueError('Enter valid Python import statements.') from exc
    if any(not isinstance(node, (ast.Import, ast.ImportFrom)) or
           (isinstance(node, ast.ImportFrom) and node.level) for node in tree.body):
        raise ValueError('Only import and from ... import statements are allowed.')
    return value.strip()


def coding_instance(record, settings, difficulty, runner=None, stdin_text="", defer_input=False, imports=""):
    if not isinstance(stdin_text, str) or len(stdin_text.encode("utf-8")) > 65536:
        raise ValueError("Program input must be text up to 64 KB.")
    stdin_text = stdin_text.replace("\r\n", "\n")
    runner = runner or run_in_sandbox
    if len(record['original_code']) > 10000:
        raise InvalidQuestionError('Code practice supports blocks up to 10,000 characters.')
    try:
        code, changes = varied_code(record['original_code'])
        prefix = validate_imports(imports)
        if prefix:
            code = prefix + '\n' + code
    except SyntaxError as exc:
        raise InvalidQuestionError(f'Source Python syntax error: {exc.msg}') from exc
    question = dict(generated_code=code, blank_code=code, blanks=[], solutions={},
                    expected_output='', stdin_text='', changed_values=changes,
                    explanation='Fill the blanks to produce the expected output.',
                    language='python', difficulty=difficulty, needs_input=False)
    try:
        question.update(make_blanks(code, difficulty))
    except ValueError as exc:
        # Silent programs such as `pass` have no blank candidates. Classify their
        # output before reporting that the syntax cannot become an exercise.
        prepare_output(question, settings, stdin_text, runner, defer_input)
        raise InvalidQuestionError(str(exc)) from exc
    return prepare_output(question, settings, stdin_text, runner, defer_input)


def prepare_output(question, settings, stdin_text='', runner=None, defer_input=True):
    if not isinstance(stdin_text, str) or len(stdin_text.encode('utf-8')) > 65536:
        raise ValueError('Program input must be text up to 64 KB.')
    stdin_text = stdin_text.replace('\r\n', '\n')
    runner = runner or run_in_sandbox
    def execute(source):
        return runner(source, settings, stdin_text=stdin_text) if stdin_text else runner(source, settings)
    first = execute(question['generated_code'])
    if 'EOFError' in first.stderr and defer_input:
        return dict(question, needs_input=True, stdin_text=stdin_text, expected_output='')
    second = execute(reconstruct(question, question['solutions'])) if first.successful else first
    for result in (first, second):
        if result.timed_out:
            raise InvalidQuestionError('Code exceeded the sandbox time limit.')
        if result.output_limited:
            raise InvalidQuestionError('Code produced too much output for the sandbox.')
        if not result.successful:
            detail = next((line for line in reversed(result.stderr.splitlines()) if line.strip()), 'No error details returned.')
            if 'EOFError' in result.stderr:
                raise InvalidQuestionError('This code needs more program input. Enter one response per line in Program input.')
            raise InvalidQuestionError('Code failed in the sandbox: ' + detail[:300])
    if first.stdout != second.stdout:
        raise InvalidQuestionError('Code produced different output on repeated runs.')
    if not first.stdout.strip():
        raise NoOutputError('This code produces no output.')
    return dict(question, expected_output=first.stdout, stdin_text=stdin_text, needs_input=False)


def grade_coding(question, answers, settings, runner=None):
    runner = runner or run_in_sandbox
    code = reconstruct(question, answers)
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return dict(correct=False, status='syntax_error', stdout='', stderr=exc.msg,
                    expected_output=question['expected_output'])
    try:
        stdin_text = question.get('stdin_text', '')
        result = runner(code, settings, stdin_text=stdin_text) if stdin_text else runner(code, settings)
    except (OSError, RuntimeError):
        return dict(correct=False, status='sandbox_failure', stdout='', stderr='Sandbox unavailable. Check Docker Desktop and retry.',
                    expected_output=question['expected_output'])
    if result.timed_out:
        status = 'timeout'
    elif result.output_limited:
        status = 'output_limit'
    elif result.exit_code:
        status = 'runtime_error'
    elif result.stdout == question['expected_output']:
        status = 'correct'
    else:
        status = 'incorrect_output'
    error = '\n'.join(line for line in result.stderr.splitlines() if line and not line.lstrip().startswith(('File ', 'Traceback')))[-1000:]
    if 'EOFError' in result.stderr:
        error = 'The program requested more input lines than this question provides. Check your answer or start over with more Program input.'
    return dict(correct=status == 'correct', status=status, stdout=result.stdout, stderr=error,
                expected_output=question['expected_output'], exit_code=result.exit_code,
                timed_out=result.timed_out, output_limited=result.output_limited)
