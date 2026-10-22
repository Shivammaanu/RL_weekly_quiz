# RL Weekly Quiz

A Streamlit quiz app built from the weekly Reinforcement Learning assignment solutions (Prof. B. Ravindran). It holds two separate question sets, each organised by week with the official answers and explanations:

| Question set | Weeks | Questions |
|---|---|---|
| 2026 | 12 | 113 |
| 2025 | 12 | 106 |

## Features

- **Question set switch** (2026 / 2025) at the top of the sidebar. Each year has its own progress, scores, exam timers and attempt history; nothing is shared between years.
- **Week selector** in the sidebar, with each week's status (not started, in progress, complete).
- **Shuffle questions & options**: automatically enabled by default on each page of questions. Randomizes the questions for that week and the options (A, B, C, D) inside each question; deselecting either toggle returns the content immediately to its original order. A **Reshuffle** button generates a fresh randomized arrangement.
- **Practice mode**: check each answer as you go and see the explanation straight away.
- **Exam mode**: answers stay hidden until you submit. An optional time limit (90 seconds per question) shows a live countdown and submits automatically when time runs out. After submitting you get a score summary and a review of every question, with a filter for the ones you missed.
- **Multi-select questions** are marked "Select all that apply" and are only scored correct when every right option, and no wrong one, is chosen.
- **Results dashboard**: total questions, answered, correct, incorrect and score; a score-and-completion chart by week; a correct vs. incorrect breakdown; and an attempt history chart.
- **Compare years**: once you have answers in both years, the dashboard shows a side-by-side chart of weekly scores. The scores themselves stay separate.
- **Progress bar** for the selected year, plus **Retry this week** and **Reset all of &lt;year&gt;** buttons. Resetting one year never touches the other.
- Maths in questions and explanations renders as LaTeX, and questions that depend on a diagram show it above the question.

## Project structure

```
rl-weekly-quiz/
├── app.py                 # the Streamlit app
├── questions/
│   ├── 2025.json          # 2025 question set (106 questions)
│   └── 2026.json          # 2026 question set (113 questions)
├── images/
│   └── 2026/              # diagrams used by 2026 questions
├── requirements.txt       # Python dependencies
├── .streamlit/config.toml # theme colour
├── .gitignore
└── README.md
```

## Run it locally

You need Python 3.9 or newer.

```bash
cd rl-weekly-quiz
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501.

## Deploy for free on Streamlit Community Cloud

### 1. Put the code on GitHub

1. Sign in at [github.com](https://github.com) and click **New repository**.
2. Name it (for example `rl-weekly-quiz`), set it to **Public**, and click **Create repository**. Public repos are the simplest option; private repos also work once you grant Streamlit access to them.
3. Upload the files. Either drag the contents of `rl-weekly-quiz/` onto the repository page using **Add file → Upload files**, or use git:

   ```bash
   cd rl-weekly-quiz
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/rl-weekly-quiz.git
   git push -u origin main
   ```

   `app.py`, `requirements.txt` and the `questions/` and `images/` folders must sit at the top level of the repository (or together in the same subfolder). If you upload through the website, drag the folders themselves so their structure is kept. The app checks at startup and shows an error naming any missing question file or image. If you upload through the website, check that the hidden `.streamlit` folder came across too; it only sets the theme colour, so the app works without it.

### 2. Connect Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and choose **Continue with GitHub**.
2. Authorise Streamlit to access your GitHub account when prompted.
3. Click **Create app**, then choose **Deploy a public app from GitHub** (wording may vary slightly).
4. Fill in the form:
   - **Repository**: `<your-username>/rl-weekly-quiz`
   - **Branch**: `main`
   - **Main file path**: `app.py` (or `subfolder/app.py` if you put it in a subfolder)
   - **App URL**: optionally choose a custom subdomain, such as `rl-weekly-quiz.streamlit.app`
5. Optionally open **Advanced settings** and pick the Python version (3.11 or 3.12 are good choices).
6. Click **Deploy**. The first build takes a few minutes while dependencies install.

When it finishes, your app is live at its `*.streamlit.app` URL, and anyone with the link can use it.

### 3. Update the app

Push changes to the `main` branch (or edit files on GitHub) and Community Cloud redeploys automatically within a minute or so.

### Good to know

- **Progress is per browser session.** Scores live in `st.session_state`, so refreshing the page or closing the tab starts fresh, and every visitor has their own independent progress. Saving progress permanently would need a database or user accounts.
- **Sleeping apps.** Free apps go to sleep after a period without visitors. The next visitor sees a "wake up" button and the app restarts in under a minute.
- **Build errors.** Open **Manage app** in the bottom-right corner of the deployed app to see the logs. Most failures come from a missing file or a typo in `requirements.txt`.

## Editing the questions

Each year lives in its own file, `questions/<year>.json`:

```json
{
  "year": 2026,
  "title": "Reinforcement Learning — 2026 Assignments",
  "source": "2026 assignment solutions 1–12, Reinforcement Learning (Prof. B. Ravindran)",
  "weeks": [
    {
      "week": 6,
      "title": "TD Learning, Q-learning, SARSA & UCT",
      "questions": [
        {
          "year": 2026,
          "week": 6,
          "id": "2026-w06q07",
          "question": "Consider CliffWorld (shown above). ...",
          "options": {"A": "Q-learning finds the optimal (red) path.", "B": "...", "C": "...", "D": "..."},
          "correct_answer": ["A", "D"],
          "type": "multiple",
          "explanation": "Q-learning is off-policy ...",
          "images": ["images/2026/w06q07_cliffworld.png"]
        }
      ]
    }
  ]
}
```

- `options` can have anywhere from 2 to 8 letters.
- `correct_answer` is always a list. `"type": "single"` shows radio buttons; `"type": "multiple"` shows checkboxes marked "Select all that apply" (you can use it with a single correct answer too, so the input type doesn't give the answer away).
- `id` must be unique across **all** files. The `<year>-wWWqQQ` pattern guarantees this.
- `images` is optional: a list of paths relative to `app.py`.
- Text supports Markdown and LaTeX (`$\gamma$`). In JSON, backslashes must be doubled: `"$\\gamma$"`.

**Adding a new year:** create `questions/2027.json` in the same format and push it. It appears in the Question set switch automatically, newest year first, with its own separate progress.

The app checks every file at startup and reports duplicate IDs, answers that don't match an option, or missing images.

To change the exam time budget, edit `SECONDS_PER_QUESTION` near the top of `app.py`.

## Notes on the source material

- 2026 Week 2 Q10 and Week 5 Q7 have duplicate answer options in the original assignments; they are kept as written.
- 2026 Weeks 5 and 12 state that one or more choices may be correct, so all their questions use checkboxes.
- Each year follows its own official answer key, even where a similar question was keyed differently in the other year.
