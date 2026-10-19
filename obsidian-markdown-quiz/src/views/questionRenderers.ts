/** Multiple-choice, coding and recovery controls used by both quiz surfaces. */
import type { SessionController } from '../quiz/session';
import { mountBlankEditor } from './CodeBlankEditor';

/** Shared recovery controls for sidebar and inline sessions. */
export function renderSessionError(host: HTMLElement, controller: SessionController, fallback = '', disabled = controller.busy): string {
  const message = controller.error || controller.state?.preparation_error || fallback;
  if (!message) return '';
  host.createEl('p', {text: message, cls: 'mq-error', attr: {role: 'alert'}});
  const button = (text: string, action: 'skip' | 'retry') => {
    const element = host.createEl('button', {text});
    element.disabled = disabled;
    element.addEventListener('click', () => void controller.perform(action));
  };
  if (controller.state && !controller.state.complete) button('Skip question', 'skip');
  if (controller.state?.preparation_error) button('Retry question', 'retry');
  return message;
}

function masteryText(score: number, due?: string) {
  const level = score >= 4 ? 'Mastered' : score >= 2 ? 'Familiar' : score > 0 ? 'Learning' : 'New';
  if (!due) return `Mastery: ${level}`;
  const date = new Date(due), now = new Date(), tomorrow = new Date(); tomorrow.setDate(now.getDate() + 1);
  const label = date <= now ? 'Now' : date.toDateString() === tomorrow.toDateString() ? 'Tomorrow' : date.toLocaleDateString();
  return `Mastery: ${level} · Review due: ${label}`;
}

export function renderCoding(host: HTMLElement, controller: SessionController) {
  const question = controller.state?.question;
  if (!question || question.type !== 'coding') return () => {};
  host.createEl('small', {text: masteryText(question.mastery, question.next_review)});
  const difficultyLabel = host.createEl('label', {cls: 'mq-field', text: 'Difficulty'});
  const difficulty = difficultyLabel.createEl('select', {attr: {'aria-label': 'Coding difficulty'}});
  for (const value of ['easy', 'medium', 'hard']) difficulty.createEl('option', {value, text: value});
  difficulty.value = controller.state?.difficulty ?? question.difficulty;
  difficulty.disabled = controller.busy;
  difficulty.addEventListener('change', () => void controller.perform('difficulty', {difficulty: difficulty.value}));
  if (question.attempts.length) host.createEl('small', {text: 'Difficulty changes apply to the next question.'});
  const label = host.createEl('label', {cls: 'mq-field', text: 'Program input'});
  const input = label.createEl('textarea', {attr: {'aria-label': 'Program input', placeholder: question.needs_input ? 'One response per line' : ''}});
  input.rows = 3; input.maxLength = 65536;
  input.value = question.input_draft ?? question.stdin_text ?? '';
  input.disabled = controller.busy || question.completed || !!question.attempts.length || (!question.needs_input && !question.stdin_text);
  input.addEventListener('input', () => { question.input_draft = input.value; });
  if (question.needs_input || question.stdin_text) {
    const apply = host.createEl('button', {text: 'Apply program input'});
    apply.disabled = controller.busy || question.completed || !!question.attempts.length;
    apply.addEventListener('click', () => void controller.perform('input', {stdin_text: input.value}));
  }
  if (question.needs_input) host.createEl('p', {text: 'This program needs input. Add enough responses and apply them to calculate the expected output.', attr: {role: 'status'}});
  let answers = {...question.draft};
  const run = () => { if (!controller.busy && !question.completed && !question.needs_input) void controller.answer({answers}); };
  const editor = mountBlankEditor(host, question, value => { answers = value; controller.draft(value); }, run, controller.busy || question.completed);
  answers = editor.model.answers();
  host.createEl('strong', {text: 'Expected output'});
  host.createEl('pre', {text: question.expected_output});
  const button = host.createEl('button', {text: question.result && !question.completed ? 'Try again' : 'Run answer'});
  button.disabled = controller.busy || question.completed || !!question.needs_input; button.addEventListener('click', run);
  host.createEl('small', {text: 'Tab: next blank · Shift+Tab: previous · Ctrl+Enter: run · Enter: new line'});
  if (question.result) {
    const result = question.result;
    const labels: Record<string, string> = {correct: 'Correct output', incorrect_output: 'Incorrect output', syntax_error: 'Syntax error',
      runtime_error: 'Runtime error', timeout: 'Time limit exceeded', output_limit: 'Output limit exceeded', sandbox_failure: 'Sandbox unavailable', skipped: 'Skipped'};
    host.createEl('p', {text: labels[result.status] ?? result.status, cls: result.correct ? 'mq-success' : 'mq-error', attr: {role: 'status'}});
    if (result.stdout !== undefined) { host.createEl('strong', {text: 'Received output'}); host.createEl('pre', {text: result.stdout || '(no output)'}); }
    if (result.stderr) host.createEl('pre', {text: result.stderr, cls: 'mq-error'});
    host.createEl('small', {text: `${result.attempts} run(s). Feedback applies to the completed program; more than one blank may need correction.`});
  }
  return editor.dispose;
}

export function renderMultipleChoice(host: HTMLElement, controller: SessionController) {
  const q = controller.state?.question;
  if (!q || q.type !== 'multiple-choice') return;
  host.createEl('small', {text: masteryText(q.mastery, q.next_review)});
  host.createEl('p', {text: q.prompt, cls: 'mq-prompt'});
  const choices = host.createDiv({cls: 'mq-choices'});
  const incorrect = new Set(q.attempts.filter(a => !a.correct).map(a => a.selected_answer_id));
  q.answers.forEach((answer, index) => {
    const button = choices.createEl('button', {text: `${index + 1}. ${answer.text}`});
    button.disabled = controller.busy || q.completed || incorrect.has(answer.id);
    if (incorrect.has(answer.id)) button.classList.add('mq-wrong');
    if (q.result?.correct_answer_id === answer.id) button.classList.add('mq-correct');
    button.addEventListener('click', () => void controller.answer({answer_id: answer.id}));
  });
  if (q.result) {
    host.createEl('p', {text: q.result.correct ? 'Correct' : q.completed ? 'Incorrect after two attempts' : 'Incorrect. Try one more answer.', attr: {role: 'status'}});
    if (q.result.explanation) host.createEl('p', {text: q.result.explanation});
  }
}
