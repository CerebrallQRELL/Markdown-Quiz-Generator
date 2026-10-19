"""Terminal presentation only; application operations live in the backend."""
import argparse
from dataclasses import asdict, replace
import json
import logging
import random

from .backend import QuizBackend
from .config import load_settings, save_settings
from .quiz.spaced_repetition import select_question
from .quiz.selection import available_tags, filter_tags
from .notes.storage import reset_quiz_data
from .services.sandbox import check_sandbox_available


def choose(label, choices, default=1):
    print('\n' + label)
    for index, choice in enumerate(choices, 1):
        print(f'{index}. {choice}')
    while True:
        answer = input(f'Choice [{default}]: ').strip() or str(default)
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return int(answer) - 1
        print('Enter a listed number.')


def select_tags(records):
    tags = available_tags(records)
    print('\nAvailable tags:')
    for i, tag in enumerate(tags, 1):
        print(f'{i}. {tag}')
    while True:
        value = input('Tags (numbers separated by commas; Enter = All): ').strip()
        if not value:
            return filter_tags(records)
        parts = value.replace(',', ' ').split()
        if all(v.isdigit() and 1 <= int(v) <= len(tags) for v in parts):
            return filter_tags(records, [tags[int(v) - 1] for v in parts])
        print('Enter available tag numbers.')


def quiz_length(default):
    while True:
        value = input(f'Quiz length [{default}] (0 = until quitting): ').strip() or str(default)
        if value.isdigit():
            return int(value)
        print('Enter a nonnegative whole number.')


def play_terms(backend):
    records = select_tags(backend.terms)
    if not records:
        print('No matching terms. Rescan Markdown first.')
        return
    direction = ['random', 'forward', 'reverse'][choose('Question direction',
        ['Random', 'Term → Definition', 'Definition → Term'])]
    length = quiz_length(backend.settings.default_quiz_length)
    count, previous = 0, None
    while records and (length == 0 or count < length):
        eligible = [r for r in records if r['source_id'] != previous] or records
        record = select_question(eligible)
        try:
            question = backend.term_question(record, direction)
        except (ValueError, RuntimeError) as exc:
            print(f"Skipping {record['term']}: {exc}")
            records.remove(record)
            continue
        print('\n' + question['prompt'])
        for letter, choice in zip('ABCD', question['choices']):
            print(f'{letter}. {choice}')
        while True:
            answer = input('Answer A–D (q = quit): ').strip().upper()
            if answer == 'Q':
                return
            if answer in ('A', 'B', 'C', 'D'):
                break
            print('Enter A, B, C, D, or q.')
        correct = backend.answer_term(question, 'ABCD'.index(answer))
        print('Correct!' if correct else 'Incorrect. Correct answer: ' + question['choices'][question['correct_index']])
        count += 1
        previous = record['source_id']


def play_code(backend):
    records = select_tags(backend.codes)
    if not records:
        print('No matching Python blocks. Rescan Markdown first.')
        return
    check_sandbox_available(backend.settings)
    modes = ['easy', 'medium', 'hard', 'random']
    mode = modes[choose('Code difficulty', ['Easy', 'Medium', 'Hard', 'Random'],
                        modes.index(backend.settings.default_code_difficulty) + 1)]
    length = quiz_length(backend.settings.default_quiz_length)
    count = 0
    while records and (length == 0 or count < length):
        record = select_question(records)
        difficulty = random.choice(modes[:3]) if mode == 'random' else mode
        try:
            backend.code_question(record, difficulty)
            while True:
                print(f"\n{record['source_file']} — {difficulty}\n{record['blank_code']}")
                print('Expected output:\n' + record['expected_output'])
                answer = input('Fill <BLANK> (:q quit, :r regenerate, :multi multiline): ')
                if answer == ':q':
                    return
                if answer == ':r':
                    backend.code_question(record, difficulty, regenerate=True)
                    continue
                if answer == ':multi':
                    print('Enter replacement lines; finish with :end on its own line.')
                    lines = []
                    while (line := input()) != ':end':
                        lines.append(line)
                    answer = '\n'.join(lines)
                correct, result = backend.answer_code(record, answer)
                print('\nProgram output:\n' + (result.stdout if result.stdout else '(no output)'))
                print('Correct!' if correct else 'Incorrect. Expected output:\n' + record['expected_output'])
                if result.stderr:
                    print('Errors:\n' + result.stderr)
                if result.timed_out or result.output_limited:
                    print('Sandbox time/output limit exceeded.')
                break
        except (ValueError, RuntimeError) as exc:
            print(f'Skipping code block: {exc}')
            records.remove(record)
        count += 1


def manage_terms(backend):
    if not backend.terms:
        print('No stored terms. Rescan Markdown first.')
        return
    labels = [r['term'] + f" ({r['source_file']})" + (' [inactive]' if not r.get('active') else '') for r in backend.terms]
    selected = choose('Stored terms', labels + ['Back'])
    if selected == len(labels):
        return
    record = backend.terms[selected]
    while True:
        action = choose('Term options', ['View term', 'Regenerate wrong answers', 'View mastery',
            'View statistics', 'Reset mastery', 'Back'])
        if action == 0:
            print(json.dumps(record, indent=2, ensure_ascii=False))
        elif action == 1:
            backend.regenerate_term(record)
            print('Wrong answers regenerated; progress preserved.')
        elif action == 2:
            print(f"Mastery: {record['mastery']}; next review: {record.get('next_review')}")
        elif action == 3:
            print(f"Correct: {record['correct_count']}; incorrect: {record['incorrect_count']}; last seen: {record.get('last_seen')}")
        elif action == 4:
            backend.reset(record)
            print('Mastery reset; historical statistics preserved.')
        else:
            return


def edit_settings(backend):
    values = asdict(backend.settings)
    keys = list(values)
    index = choose('Settings (environment overrides apply on restart)',
        [f'{key}: {values[key]}' for key in keys] + ['Back'])
    if index == len(keys):
        return backend
    key = keys[index]
    if key == 'data_path':
        print('To select another data directory, restart with DATA_PATH or --data. Data is not moved automatically.')
        return backend
    value = type(values[key])(input(f'New {key}: ').strip())
    updated = replace(backend.settings, **{key: value}).validate()
    save_settings(updated)
    backend.settings = updated
    print('Settings saved. Rescan after changing vault_path.')
    return backend


def main(argv=None):
    parser = argparse.ArgumentParser(description='Markdown Quiz Generator')
    parser.add_argument('--vault', help='Markdown notes directory')
    parser.add_argument('--data', help='JSON data directory')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('command', nargs='?', choices=['rescan', 'terms', 'tags', 'term-quiz', 'code-quiz', 'reset-json'])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format='%(levelname)s: %(message)s')
    try:
        if args.data:
            # Load the settings belonging to the chosen data directory.
            import os
            os.environ['DATA_PATH'] = args.data
        settings = load_settings()
        if args.vault:
            settings.vault_path = args.vault
        if args.command == 'reset-json':
            kind = ['terms', 'code', 'all'][choose('Reset JSON data',
                ['Multiple-choice data', 'Code quiz data', 'Both'], default=3)]
            print(f'This clears {kind} quiz data, including generated questions, mastery, and history.')
            print(f'Data folder: {settings.data_path}. A backup will be saved; settings are preserved.')
            if input('Type RESET to continue: ').strip() != 'RESET':
                print('Reset canceled.')
                return 0
            backup = reset_quiz_data(settings.data_path, kind)
            print(f'Quiz JSON reset. Backup: {backup}')
            print('The quiz launchers will read your Markdown again on their next run.')
            return 0
        backend = QuizBackend(settings)
        save_settings(settings)
        if args.command in ('term-quiz', 'code-quiz'):
            rows = backend.terms if args.command == 'term-quiz' else backend.codes
            if not rows:
                for error in backend.rescan():
                    print(error)
            (play_terms if args.command == 'term-quiz' else play_code)(backend)
            return 0
        if args.command == 'rescan':
            for error in backend.rescan():
                print(error)
            print(f'{len(filter_tags(backend.terms))} active terms; {len(filter_tags(backend.codes))} active Python blocks.')
            return 0
        if args.command in ('terms', 'tags'):
            print(json.dumps(available_tags(backend.terms) if args.command == 'tags' else backend.terms, indent=2, ensure_ascii=False))
            return 0
        while True:
            action = choose('Markdown Quiz Generator', ['Term Quiz', 'Code Quiz', 'Rescan Markdown',
                'View Terms', 'Settings', 'Exit'])
            try:
                if action == 0:
                    play_terms(backend)
                elif action == 1:
                    play_code(backend)
                elif action == 2:
                    for error in backend.rescan():
                        print(error)
                    print(f'Scan complete: {len(filter_tags(backend.terms))} terms, {len(filter_tags(backend.codes))} Python blocks.')
                elif action == 3:
                    manage_terms(backend)
                elif action == 4:
                    edit_settings(backend)
                else:
                    return 0
            except (ValueError, RuntimeError, OSError) as exc:
                print(f'Unable to complete action: {exc}')
    except (EOFError, KeyboardInterrupt):
        print('\nGoodbye. Answered questions have been saved.')
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'Error: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
