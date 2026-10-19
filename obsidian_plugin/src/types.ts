/** Shared plugin settings and HTTP request/response shapes. */
export type Direction = 'random' | 'forward' | 'reverse' | 'source';
export type Difficulty = 'easy' | 'medium' | 'hard';
export type QuizLength = number | 'all' | 'until';

export interface Settings {
  generationProvider: 'ollama' | 'api';
  apiUrl: string;
  apiModel: string;
  disabledLibraries: string[];
  quizType: QuizType;
  collapsed: Record<string, boolean>;
  sessionIds: Record<string, string>;
  dateFrom: string;
  dateTo: string;
  currentOnly: boolean;
  connectionMode: 'local' | 'server';
  vaultKey: string;
  backendUrl: string;
  pythonPath: string;
  pythonImports: string;
  ollamaModel: string; // Legacy setting retained for migration.
  quizModels: Partial<Record<QuizType, string>>;
  excludeTags: string[];
  tagHistory: Record<string, {count: number; last: number}>;
  length: QuizLength;
  direction: Direction;
  difficulty: Difficulty;
  dueOnly: boolean;
  rememberTags: boolean;
  tags: string[];
  inline: boolean;
  reading: boolean;
  livePreview: boolean;
  autoSync: boolean;
  debounceMs: number;
  timeoutSeconds: number;
  initialized: boolean;
}
export interface Health {
  status: string; version: string; api_version: number; ollama: boolean; sandbox: boolean;
  service?: string; capabilities?: string[]; managed?: boolean;
}
export interface VaultConnection { vault_id: string; vault_path: string }
export interface ModelsResponse { models: string[] }
export interface LibrariesResponse { packages: string }
export interface ResetResponse { ok: boolean; message: string }
export interface Stats { due: number; mastered: number; learning: number; new: number; correct: number; incorrect: number; total: number }
export interface Summary { answered: number; correct: number; incorrect: number; percent: number; improved: number; missed: string[] }
export interface CodeBlock { code: string; occurrence: number; from: number; to: number; startLine: number; endLine: number }

export type QuizType = 'multiple-choice' | 'coding';
export type QuizAction = 'start' | 'resume' | 'answer' | 'draft' | 'abandon'
  | 'skip' | 'next' | 'input' | 'difficulty' | 'retry' | 'regenerate';
export type AnswerPayload = {answer_id: string} | {answers: Record<string, string>};
export interface QuestionBase {
  question_id: string; source_id: string; type: QuizType; source_file: string;
  source_line: number; tags: string[]; mastery: number; next_review?: string;
  completed: boolean; attempts: AttemptResult[]; result: AttemptResult | null;
  draft: Record<string, string>;
}
export interface MultipleChoiceQuestion extends QuestionBase {
  type: 'multiple-choice'; prompt: string; answers: {id: string; text: string}[];
  direction: Direction;
}
export interface CodingQuestion extends QuestionBase {
  type: 'coding'; language: string; difficulty: Difficulty; blank_code: string;
  stdin_text?: string; needs_input?: boolean; input_draft?: string;
  blanks: {id: string; marker: string; multiline: boolean}[]; expected_output: string;
}
export type QuizQuestion = MultipleChoiceQuestion | CodingQuestion;
export interface AttemptResult {
  question_id: string; source_id: string; question_type: QuizType;
  correct: boolean; completed: boolean; attempts: number; response_time_ms: number;
  timestamp: string; status: string; first_attempt_correct: boolean;
  mastery: number; next_review?: string; selected_answer_id?: string;
  correct_answer_id?: string; explanation?: string; stdout?: string; stderr?: string;
  expected_output?: string; run_count?: number;
}
export interface QuizSession {
  preparation_error?: string;
  notice?: string; difficulty?: Difficulty;
  session_id: string; quiz_type: QuizType; question: QuizQuestion | null;
  complete: boolean; index: number; total: number | null;
  progress: Summary & {first_correct: number; retry_correct: number; failed_runs: number; skipped: number};
  result: AttemptResult | null;
}
export interface Selection {
  quiz_type: QuizType; tags: string[]; exclude_tags: string[]; date_from: string; date_to: string;
  due_only: boolean; source_file?: string; difficulty: Difficulty; direction: Direction;
  python_imports?: string;
  length: QuizLength; question_ids?: string[]; code_hash?: string; occurrence?: number;
}
export interface Catalog { count: number; tags: string[]; stats: Stats }
