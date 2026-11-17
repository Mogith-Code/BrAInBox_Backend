# Question data

| File | Imported by | Format |
|---|---|---|
| `question_bank.json` | `scripts/import_question_bank.py` | a list of MCQs (see the script's docstring) |
| `<year>_<part>.json`, e.g. `2023_part_1.json` | `scripts/import_past_papers.py` | **one past paper**, below |
| `example_past_paper.json` | (example only, year 1990) | a 2-question Paper I in the format below. Use `--dry-run` with it; don't import it into the team database (it would take the 1990 Paper I numbers 1 and 2) |

## Past paper JSON (`scripts/import_past_papers.py`)

One file = one paper (one part). Run `scripts/seed_syllabus.py` first, then:

```bash
python scripts/import_past_papers.py --file data/questions/2023_part_1.json --dry-run   # check only
python scripts/import_past_papers.py --file data/questions/2023_part_1.json
```

```json
{
  "year": 2023,
  "paper_part": "part_1",
  "title": "2023 A/L Biology Paper I (MCQ)",
  "duration_minutes": 120,
  "questions": [
    {
      "number": "1",
      "topic": "Cell Structure",
      "question": "Which organelle is the main site of ATP production?",
      "options": ["Ribosome", "Mitochondrion", "Golgi apparatus", "Lysosome", "Peroxisome"],
      "correct_answer": "Mitochondrion",
      "marks": 1,
      "difficulty": "easy",
      "explanation": "Oxidative phosphorylation happens in the mitochondria."
    }
  ]
}
```

### Paper fields

| Field | Required | Rules |
|---|---|---|
| `year` | yes | whole number, 1990-2100 |
| `paper_part` | yes | `part_1` (Paper I, MCQ) · `part_2a` (Paper II part A, structured) · `part_2b` (Paper II part B, essay). It sets the type of every question |
| `title` | no | default `"<year> A/L Biology Paper I (MCQ)"` (etc.). The paper is found again by year + title |
| `duration_minutes` | no | positive whole number |
| `questions` | yes | non-empty list, in paper order |

### Question fields

| Field | Required | Rules |
|---|---|---|
| `number` | yes | the number in the paper, max 10 characters: `"23"`, `"5(b)"`. Unique in the file |
| `topic` | yes | a seeded topic title (exact, else the one title that contains it / is contained in it; case-insensitive) |
| `question` | yes | the question text (Markdown allowed) |
| `options` | `part_1` only | 4 or 5 different texts, in order A-E. Not allowed for Paper II |
| `correct_answer` | `part_1` only | exactly the text of one option |
| `marks` | Paper II: yes; MCQ: no (default 1) | positive whole number |
| `difficulty` | no | `easy` · `medium` (default) · `hard` |
| `explanation` | no | shown to students after they answer |

### What the import does

* Checks the whole file first. Any problem (or a topic that matches no seeded topic) means **nothing is written**;
  every problem is printed with its question number.
* Creates approved questions with `source = "past_paper"`, `year`, `paper_part`, `question_number`, the topic and
  its unit; MCQs get their options (`mcq_options`, the right one marked correct).
* Creates one `papers` row (`paper_type = "past_paper"`, approved, `total_marks`, `unit_ids`) and links the
  questions in file order (`paper_questions`).
* **Re-running is safe.** A question that already exists for the same year + part + number is reused as it is
  (edit it in the admin question bank, not by re-importing). The paper with the same year + title is reused and
  only missing questions are linked, at the end.
* Misconceptions for the wrong options are not part of this file: add them in the admin MCQ mapping editor (the
  AI can suggest them: `POST /api/v1/admin/questions/{id}/misconception-suggestions`).
