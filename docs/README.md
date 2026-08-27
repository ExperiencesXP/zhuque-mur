# Zhūquè-Mur

**Zhūquè-Mur** automates a *legal* reimplementation process: check the license, keep analysis and implementation apart with isolated AI agents, and produce code you can license as your own.

The name is the image. Zhūquè (朱雀, the vermilion bird) and *mur* (wall): a firewall between two rooms.

This is process design, not an algorithm. A model that “rewrites a GitHub repo” is often a license violation in costume. Clean-room is the older engineering discipline: one team *describes* behaviour, another team *writes* new code, and the two must not share source.

## The wall

1. **License check.** Is the original something you may even look at for this purpose?
2. **Isolation.** The analyst may read the original and write notes. The specifier turns those notes into a requirements spec and must not read the original. The implementer may read the spec and write new code — never the original, never the notes.
3. **Independent license.** The output can carry *your* license only if it is not a derivative of the source text.

The spec is the only bridge. That is the same idea as a kravspec in DDU: requirements, not a copy.

The tool enforces the rooms on disk. The clean-room agent physically cannot open `dirty/` or `analysis/`. That is not a legal audit. Models are trained on other people’s code; isolation here does not erase that.

## Rooms

```
src/workspace/<owner>__<repo>/
  dirty/       original source          — analyst only
  analysis/    brief + notes            — analyst and specifier
  spec/        requirements spec        — the only bridge
  clean/       new implementation       — implementer only
  LICENSE_VERDICT.md
  run.log
  session.json implementer transcript   — resume after interrupt
```

## Setup

```bash
poetry install
copy .env.example .env          # then put real keys in .env
```

Sign in from the CLI (preferred) or put keys in `.env`:

```
auth login xai          # SuperGrok / X Premium+ device-code OAuth
auth key openai         # paste an official API key
auth byok neuralwatt    # Neuralwatt, OpenCode Zen, OpenRouter, Ollama, …
auth byok custom        # any OpenAI-compatible base URL
auth import             # reuse .env and ~/.local/share/opencode/auth.json
```

OAuth is only offered where the vendor publishes a third-party or native-app flow (today: xAI). ChatGPT Codex client impersonation and Claude Pro/Max subscription OAuth are not implemented — those vendors do not allow that for third-party tools. Use an API key.

Credentials are stored in `~/.zhuque-mur/auth.json` (mode 600). After a gateway login:

```
model neuralwatt/deepseek-v4-flash
model opencode/kimi-k2.6
```

`.env` still works:

- `XAI_API_KEY` — default model is `grok-4.6` via [xAI](https://docs.x.ai)
- `GITHUB_TOKEN` — optional but recommended (higher GitHub API rate limits)
- plus `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `NEURALWATT_API_KEY`, `OPENCODE_API_KEY`, …

```bash
.\scripts\install-path.ps1   # once: shims in ~/.local/bin
zhuque
```

`zhuque` is the short name. `zhuque-mur`, `zhu-mur`, and `zhu` all launch the same CLI. After `poetry install` you can also use `poetry run zhuque`.

Tests: `poetry run python -m unittest discover -s tests`

## Commands

| Command | Role |
|---|---|
| `target owner/repo` | Choose the GitHub repository |
| `inspect` / `license` | License verdict and metadata |
| `fetch` | Download the original into `dirty/` |
| `analyze` | Dirty room: brief + reverse-engineering notes |
| `specify` | Airlock: spec from notes only |
| `implement` | Clean room: new code from the spec only (isolated tool loop) |
| `continue` / `resume` | Pick up the last (or named) workspace at the next unfinished step |
| `run` | License gate, then remaining steps (skips rooms that are already done) |
| `model` / `model list` | Show or change the model (`provider/model` for BYOK) |
| `auth` / `auth login` / `auth byok` | OAuth and bring-your-own-key |
| `rooms` / `rooms list` | Show on-disk rooms (survives restart; no live target needed) |
| `status` / `help` / `exit` | Session |

Rooms survive a restart. `continue` (or `resume`) restores the remembered workspace and runs the next unfinished step: fetch, analyze, specify, or implement. Specify and implement do not need a live GitHub target — the on-disk rooms are enough. Fetch still needs `target owner/repo`.

The implementer is a tool loop, not a one-shot rewrite. It may `read_spec`, `write_file`, `read_file`, `list_clean`, and `finish`, and it physically cannot open `dirty/` or `analysis/`. Progress is saved to `session.json` after every turn, so an interrupt or a turn cap is not a dead end: run `continue`.

## Example

You want a textbook Vigenère, not a byte-oriented clone of some `vigenere.py`.

1. The analyst writes: alphabet A–Z, key repeats, modulo 26, no Base64.
2. The specifier turns that into a kravspec.
3. The implementer writes new code. It must not open `vigenere.py`. If it does, the room is dirty.

## Pitfalls this tool does not remove

- Seeing the code yesterday and writing it today is not clean-room. Isolation is in time and in person (here: in agent and in files).
- AI does not delete the law. It makes the law harder: models have been trained on other people’s code.
- Do not claim an audit you have not done. Document the process. That is all this program claims.

Educational use only. You are responsible for how you use it.
